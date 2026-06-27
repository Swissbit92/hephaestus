"""Worked example — copy this as the starting point for a generator script.

Demonstrates every named layout. Run with `python3 example.py` (needs `python-pptx`).
The model writes a script like this from the APPROVED outline — it never hand-rolls
geometry.
"""
from deck_lib import Deck


def build(out_path: str = "example.pptx") -> str:
    d = Deck("Quarterly Data Platform Review", footer="Example Org · Confidential")

    d.title_slide("Quarterly Data Platform Review", "Q3 — engineering summary")

    d.section_divider("Where we are")

    s = d.content_slide(
        "Manual SQL joins make batch genealogy brittle",
        [
            "Each lineage query is hand-written and re-derived per analyst.",
            "No shared definition of 'batch' across teams → inconsistent results.",
            "Onboarding a new source takes ~2 weeks of glue code.",
        ],
    )
    d.notes(s, "Open on the pain the audience feels weekly: lineage is manual and fragile.")

    d.stat_tiles(
        "The cost, quantified",
        [("~2 wks", "to onboard a source"), ("0", "shared definitions"), ("3x", "rework rate")],
    )

    d.section_divider("What we propose")

    d.content_slide(
        "A modeled lineage layer removes the manual joins",
        [
            "One canonical 'batch' entity, defined once.",
            "Lineage is queried from the model, not reconstructed by hand.",
            "New sources plug into the model in days, not weeks.",
        ],
    )

    d.closing_slide("Questions?", "platform-team@example.org")
    return d.save(out_path)


if __name__ == "__main__":
    print("wrote", build())
