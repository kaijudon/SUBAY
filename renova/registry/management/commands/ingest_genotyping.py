"""ingest_genotyping — load one genotyping pipeline run's results (Slice 10).

Provenance, not orchestration: BioEdit/BLASTn/MAFFT run manually; this command is
the system-of-record loader. It is ALL-OR-NOTHING (the whole import is one
transaction — a mid-import failure rolls back with no half-written rows),
IDEMPOTENT (keyed by the input-manifest SHA-256, a re-run duplicates nothing), and
CONTENT-ADDRESSED (each raw file is stored under MEDIA_ROOT named by its SHA-256,
so identical bytes dedup). It also closes the slice-09 tube→analysis custody link
by pointing the named `ConsumptionEvent` at the created `PipelineRun`.

Manifest schema (JSON, files referenced relative to the manifest's directory)::

    {
      "tool_versions": "BioEdit 7.2; MAFFT 7.5",
      "reference_set": {"name": "Ross 2020", "citation": "...",
                        "content_sha256": "<hex>", "accessions": [...]},
      "results": [{"aliquot_id": 1, "consumption_event_id": 5,
                   "assay_type": "sanger", "entered_by": "<username>",
                   "calls": [...], "sanger": [...], "qpcr": [...]}]
    }

Helpers are kept small (cyclomatic complexity < 10); the whole row build runs
inside one `@transaction.atomic` block.
"""
import contextlib
import hashlib
import json
from pathlib import Path

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from renova.registry.models import (
    Aliquot,
    ConsumptionEvent,
    GenotypeCall,
    GenotypingResult,
    PipelineRun,
    QpcrDetail,
    QpcrProbeReading,
    ReferenceAccession,
    ReferenceSet,
    SangerDetail,
)


def _sha256(raw):
    return hashlib.sha256(raw).hexdigest()


class Command(BaseCommand):
    help = "Load one genotyping pipeline run's results (all-or-nothing, idempotent)."

    def add_arguments(self, parser):
        parser.add_argument("manifest", help="Path to the run's manifest.json")

    def handle(self, *args, manifest, **options):
        manifest_path = Path(manifest)
        raw = manifest_path.read_bytes()
        data = json.loads(raw)
        run_sha = _sha256(raw)

        if PipelineRun.objects.filter(input_manifest_sha256=run_sha).exists():
            self.stdout.write(f"Run {run_sha[:8]} already ingested; nothing to do.")
            return

        created_files = []
        try:
            with transaction.atomic():
                self._ingest(data, manifest_path.parent, run_sha, created_files)
        except (ValidationError, KeyError, ValueError, LookupError) as exc:
            self._unwind_files(created_files)
            raise CommandError(f"Ingest failed and rolled back: {exc}")

        self.stdout.write(self.style.SUCCESS(f"Ingested run {run_sha[:8]}."))

    @staticmethod
    def _unwind_files(created_files):
        for path in created_files:
            with contextlib.suppress(FileNotFoundError):
                path.unlink()

    def _ingest(self, data, bundle_dir, run_sha, created_files):
        reference_set = self._pin_reference_set(data.get("reference_set"))
        run = PipelineRun.objects.create(
            input_manifest_sha256=run_sha,
            tool_versions=data.get("tool_versions", ""),
            reference_set=reference_set,
        )
        for record in data["results"]:
            self._create_result(record, bundle_dir, run, created_files)

    @staticmethod
    def _pin_reference_set(spec):
        if spec is None:
            return None
        reference_set, _ = ReferenceSet.objects.get_or_create(
            content_sha256=spec["content_sha256"],
            defaults={"name": spec["name"], "citation": spec.get("citation", "")},
        )
        for acc in spec.get("accessions", []):
            ReferenceAccession.objects.get_or_create(
                reference_set=reference_set,
                accession=acc["accession"],
                defaults={"genotype": acc["genotype"]},
            )
        return reference_set

    def _create_result(self, record, bundle_dir, run, created_files):
        result = GenotypingResult(
            aliquot=Aliquot.objects.get(pk=record["aliquot_id"]),
            pipeline_run=run,
            assay_type=record["assay_type"],
        )
        result.full_clean(exclude=["cmv_episode_anchor"])
        result.save()
        self._create_calls(result, record)
        self._create_sanger(result, record, bundle_dir, created_files)
        self._create_qpcr(result, record)
        self._link_consumption(record, run)

    @staticmethod
    def _resolve_user(username):
        return get_user_model().objects.get(username=username) if username else None

    def _create_calls(self, result, record):
        editor = self._resolve_user(record.get("entered_by"))
        for spec in record.get("calls", []):
            call = GenotypeCall(
                result=result, locus=spec["locus"], allele=spec["allele"],
                sanger_call=spec.get("sanger_call"), entered_by=editor,
            )
            call.full_clean()
            call.save()

    def _create_sanger(self, result, record, bundle_dir, created_files):
        editor = self._resolve_user(record.get("entered_by"))
        for spec in record.get("sanger", []):
            sha = self._store_file(bundle_dir / spec["raw_ab1"], created_files)
            detail = SangerDetail(
                result=result, raw_ab1_sha256=sha, raw_ab1_path=sha,
                consensus_sequence=spec.get("consensus", ""), edited_by=editor,
            )
            detail.full_clean()
            detail.save()

    def _create_qpcr(self, result, record):
        editor = self._resolve_user(record.get("entered_by"))
        for spec in record.get("qpcr", []):
            detail = QpcrDetail.objects.create(result=result)
            for probe in spec.get("probes", []):
                self._create_probe(detail, probe, editor)

    def _create_probe(self, detail, probe, editor):
        reading = QpcrProbeReading(
            qpcr_detail=detail, probe=probe["probe"], call=probe["call"],
            entered_by=editor,
            reviewed_by=self._resolve_user(probe.get("reviewed_by")),
            reviewed_at=probe.get("reviewed_at"),
        )
        reading.full_clean()
        reading.save()

    @staticmethod
    def _store_file(src, created_files):
        """Content-addressed store: name == SHA-256, skip-if-exists dedup."""
        raw = src.read_bytes()
        sha = _sha256(raw)
        dest = Path(settings.MEDIA_ROOT) / sha
        if not dest.exists():
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(raw)
            created_files.append(dest)
        return sha

    @staticmethod
    def _link_consumption(record, run):
        ce_id = record.get("consumption_event_id")
        if ce_id is None:
            return
        ConsumptionEvent.objects.filter(pk=ce_id).update(pipeline_run=run)
