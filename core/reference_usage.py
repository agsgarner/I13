def summarize_reference_usage(final_state: dict) -> dict:
    entries = []
    for key in (
        "topology_reference_summary",
        "sizing_reference_summary",
        "netlist_reference_summary",
        "constraint_reference_summary",
        "op_point_reference_summary",
        "refinement_reference_summary",
        "verification_reference_summary",
    ):
        summary = final_state.get(key) or {}
        for bucket in ("used", "hits"):
            for item in summary.get(bucket) or []:
                if isinstance(item, dict):
                    entries.append(item)

    by_id = {}
    for entry in entries:
        ref_id = entry.get("id")
        if ref_id:
            by_id[ref_id] = entry

    def ids_for(predicate):
        return sorted(
            ref_id
            for ref_id, entry in by_id.items()
            if predicate(entry)
        )

    return {
        "reference_ids_used": sorted(by_id),
        "equations_used": ids_for(lambda item: item.get("content_type") == "design_equation" or item.get("schema") == "design_equation"),
        "templates_used": ids_for(lambda item: item.get("content_type") == "template" or "template" in str(item.get("schema", ""))),
        "heuristics_used": ids_for(lambda item: item.get("content_type") == "device_selection_heuristic" or "heuristic" in str(item.get("schema", ""))),
    }
