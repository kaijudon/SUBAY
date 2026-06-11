from django.core.validators import RegexValidator

# Subject IDs are opaque pseudonyms [S|D]CMV[R|D][NN] (e.g. SCMVR07). The system
# only validates the format — the identity map lives outside the app, held by
# SPMC clinical staff. A leading zero is significant: "07" is never coerced to 7.
subject_id_validator = RegexValidator(
    regex=r"^[SD]CMV[RD]\d{2}$",
    message="subject_id must match [S|D]CMV[R|D][NN], e.g. SCMVR07.",
)
