from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Sequence

from .executor import ExecutionError, validate_plan
from .planning import DRAFT_LAYOUTS, DraftPlanError, build_draft_plan
from .state import StateError, StateStore


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="media-janitor-draft",
        description=(
            "Generate and persist a reviewed draft filesystem plan from one approved proposal. "
            "This command never applies the plan."
        ),
    )
    parser.add_argument("proposal_id", help="Approved proposal id")
    parser.add_argument(
        "--state-dir",
        type=Path,
        default=Path("/state"),
        help="Persistent Media Janitor state directory (default: /state)",
    )
    parser.add_argument(
        "--layout",
        choices=DRAFT_LAYOUTS,
        default="author-series-title",
        help="Canonical folder layout (default: author-series-title)",
    )
    parser.add_argument(
        "--output",
        type=Path,
        help="Draft plan path. Defaults to STATE_DIR/plans/PROPOSAL_ID.json",
    )
    parser.add_argument("--pretty", action="store_true", help="Pretty-print the plan JSON")
    return parser


def _is_within(path: Path, parent: Path) -> bool:
    return path == parent or path.is_relative_to(parent)


def run(args: argparse.Namespace) -> int:
    state_dir = args.state_dir.expanduser().resolve()
    store = StateStore.from_state_dir(state_dir)
    result = build_draft_plan(store, args.proposal_id, layout=args.layout)
    validate_plan(result.plan)

    media_root = Path(result.plan.root).expanduser().resolve()
    if _is_within(store.path, media_root):
        raise DraftPlanError("State database must live outside the media root")

    output = args.output or (state_dir / "plans" / f"{args.proposal_id}.json")
    output = output.expanduser().resolve()
    if _is_within(output, media_root):
        raise DraftPlanError("Draft plan file must live outside the media root")
    if output.exists():
        raise DraftPlanError(f"Draft plan file already exists: {output}")

    output.parent.mkdir(parents=True, exist_ok=True)
    indent = 2 if args.pretty else None
    payload = result.plan.to_dict()
    encoded = json.dumps(payload, indent=indent) + "\n"

    try:
        with output.open("x", encoding="utf-8") as handle:
            handle.write(encoded)
        stored = store.save_report(
            "draft-plan",
            {
                **result.to_dict(),
                "plan_file": str(output),
            },
            root=result.plan.root,
        )
    except Exception:
        output.unlink(missing_ok=True)
        raise

    print(
        json.dumps(
            {
                "status": "drafted",
                "proposal_id": result.proposal_id,
                "candidate_sha256": result.candidate_sha256,
                "layout": result.layout,
                "source_item_path": result.source_item_path,
                "target_item_path": result.target_item_path,
                "operations": len(result.plan.operations),
                "companion_files": len(result.companion_files),
                "plan_id": result.plan.plan_id,
                "plan_file": str(output),
                "state_report_id": stored.report_id,
                "state_report_sha256": stored.payload_sha256,
                "warnings": list(result.warnings),
                "apply_performed": False,
            },
            indent=2,
        )
    )
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return run(args)
    except (DraftPlanError, ExecutionError, StateError, OSError, ValueError) as error:
        parser.exit(1, f"error: {error}\n")


if __name__ == "__main__":
    raise SystemExit(main())
