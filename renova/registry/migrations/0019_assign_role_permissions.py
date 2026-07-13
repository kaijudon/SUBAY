from django.db import migrations

# Front-end 3 (issue #3): assign the study's RBAC matrix to the four role Groups
# created in 0002. Still pure Django Groups/Permissions — no bespoke security
# code (PRD US#25/#66). Matrix (DEC on issue #3, "full-view + role actions"):
#   admin               — all registry perms (add/change/delete/view).
#   data_manager        — add/change/view on every registry model (the entry
#                         role; delete is governed by the append-only admin
#                         mixins, so no delete perm is granted).
#   reviewing_clinician — view on every registry model, plus change on the
#                         outcome-critical (four-eyes) models so it can verify.
#   data_analyst        — view only on every registry model (read-only; no
#                         add/change/delete controls surface).
OUTCOME_CRITICAL = ["cmvserology", "druglevel", "rejectionepisode", "genotypecall"]


def _ensure_registry_permissions():
    """Permissions are normally created by a post_migrate signal that fires only
    after the whole migrate run finishes — so on a FRESH database they may not
    exist yet when this data migration runs. Create them now so the querysets
    below are non-empty."""
    from django.apps import apps as global_apps
    from django.contrib.auth.management import create_permissions

    app_config = global_apps.get_app_config("registry")
    create_permissions(app_config, verbosity=0)


def assign_permissions(apps, schema_editor):
    _ensure_registry_permissions()
    Group = apps.get_model("auth", "Group")
    Permission = apps.get_model("auth", "Permission")

    reg = Permission.objects.filter(content_type__app_label="registry")

    def action(prefix):
        return reg.filter(codename__startswith=f"{prefix}_")

    Group.objects.get(name="admin").permissions.set(reg)
    Group.objects.get(name="data_manager").permissions.set(
        action("add") | action("change") | action("view")
    )
    Group.objects.get(name="data_analyst").permissions.set(action("view"))
    change_outcome = reg.filter(
        codename__in=[f"change_{m}" for m in OUTCOME_CRITICAL]
    )
    Group.objects.get(name="reviewing_clinician").permissions.set(
        action("view") | change_outcome
    )


def clear_permissions(apps, schema_editor):
    Group = apps.get_model("auth", "Group")
    for name in ("admin", "data_manager", "reviewing_clinician", "data_analyst"):
        try:
            Group.objects.get(name=name).permissions.clear()
        except Group.DoesNotExist:
            pass


class Migration(migrations.Migration):
    dependencies = [
        ("registry", "0018_slice14_safety"),
        ("auth", "0012_alter_user_first_name_max_length"),
    ]

    operations = [migrations.RunPython(assign_permissions, clear_permissions)]
