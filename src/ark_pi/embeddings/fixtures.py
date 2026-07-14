DEFAULT_ACTIVE_TEST_TEXTS = (
    "how to purify drinking water",
    "safe methods for making water drinkable",
    "how to repair a bicycle chain",
)

BUILTIN_EVALUATION_FIXTURE: dict[str, object] = {
    "schema_version": 1,
    "records": [
        {
            "id": "water-1",
            "text": (
                "Water purification methods include boiling, filtration, and chemical treatment "
                "for removing common contaminants."
            ),
        },
        {
            "id": "water-2",
            "text": (
                "Portable filters and UV treatment can improve drinking water quality when "
                "sources are uncertain."
            ),
        },
        {
            "id": "water-3",
            "text": (
                "Settling and decanting can reduce suspended particles before additional "
                "purification steps."
            ),
        },
        {
            "id": "wound-1",
            "text": (
                "Wound cleaning typically starts with gentle rinsing using clean water to "
                "remove visible debris."
            ),
        },
        {
            "id": "wound-2",
            "text": (
                "Covering a cleaned wound with a sterile dressing helps protect the area "
                "during healing."
            ),
        },
        {
            "id": "wound-3",
            "text": (
                "Monitoring for redness or swelling is a common part of basic wound care "
                "observation."
            ),
        },
        {
            "id": "electrical-1",
            "text": (
                "Electrical safety includes turning off power at the breaker before working "
                "on household wiring."
            ),
        },
        {
            "id": "electrical-2",
            "text": (
                "GFCI outlets are designed to reduce shock risk in damp locations such as "
                "kitchens and bathrooms."
            ),
        },
        {
            "id": "electrical-3",
            "text": (
                "Using insulated tools and dry gloves is a standard precaution for basic "
                "electrical maintenance."
            ),
        },
        {
            "id": "bicycle-1",
            "text": (
                "A bicycle chain may need lubrication and tension adjustment during routine "
                "maintenance."
            ),
        },
        {
            "id": "bicycle-2",
            "text": (
                "Checking derailleur alignment can help when gear shifting becomes noisy or "
                "inconsistent."
            ),
        },
        {
            "id": "bicycle-3",
            "text": (
                "Inspecting brake pads and cable tension is part of regular bicycle safety "
                "checks."
            ),
        },
    ],
    "queries": [
        {
            "query": "methods to make water safer to drink",
            "relevant_ids": ["water-1", "water-2", "water-3"],
        },
        {
            "query": "basic steps for cleaning a minor wound",
            "relevant_ids": ["wound-1", "wound-2", "wound-3"],
        },
        {
            "query": "household electrical shock prevention",
            "relevant_ids": ["electrical-1", "electrical-2", "electrical-3"],
        },
        {
            "query": "fixing bicycle drivetrain problems",
            "relevant_ids": ["bicycle-1", "bicycle-2", "bicycle-3"],
        },
    ],
}
