import math
from typing import List, Dict, Any, Union


def compute_shares(
    items: List[Dict[str, Any]],
    assignments: Union[List[Dict[str, Any]], Dict[Union[str, int], List[str]]],
    tax_minor: int,
    discount_minor: int,
    members: Union[List[str], List[Dict[str, Any]]]
) -> Dict[str, Any]:
    """
    Computes fair shares using the Largest Remainder Method (Hare-Niemeyer).
    Guarantees sum of shares EXACTLY equals total bill in minor units.
    
    items: [{id, name, price_minor, qty}]
    assignments: [{item_id, people:[names]}] or {item_id: [names]}
    tax_minor: integer minor units
    discount_minor: integer minor units
    members: list of names or member dicts
    """
    # Normalize member names
    member_names: List[str] = []
    for m in members:
        if isinstance(m, dict):
            member_names.append(m["name"])
        else:
            member_names.append(str(m))
    
    # Normalize assignments to dict: item_id -> list of names
    assign_map: Dict[Union[str, int], List[str]] = {}
    if isinstance(assignments, list):
        for a in assignments:
            item_id = a.get("item_id")
            people = a.get("people", [])
            assign_map[item_id] = people
            assign_map[str(item_id)] = people
    elif isinstance(assignments, dict):
        for k, v in assignments.items():
            assign_map[k] = v
            assign_map[str(k)] = v

    # Calculate item totals and track shares
    subtotals_float: Dict[str, float] = {name: 0.0 for name in member_names}
    own_items_detail: Dict[str, List[Dict[str, Any]]] = {name: [] for name in member_names}
    shared_items_detail: Dict[str, List[Dict[str, Any]]] = {name: [] for name in member_names}
    
    items_total_minor = 0
    for idx, item in enumerate(items):
        item_id = item.get("id", idx + 1)
        name = item.get("name", f"Item {idx + 1}")
        price = int(item.get("price_minor", 0))
        qty = int(item.get("qty", 1))
        line_total = price * qty
        items_total_minor += line_total
        
        # Find assigned people
        assigned_people = assign_map.get(item_id)
        if assigned_people is None:
            assigned_people = assign_map.get(str(item_id), [])
            
        # Filter assigned people to valid members
        valid_assigned = [p for p in assigned_people if p in member_names]
        
        if valid_assigned:
            people_count = len(valid_assigned)
            share_per_person = line_total / people_count
            is_shared = (people_count > 1)
            
            for person in valid_assigned:
                subtotals_float[person] += share_per_person
                entry = {
                    "item_id": item_id,
                    "name": name,
                    "price_minor": price,
                    "qty": qty,
                    "total_minor": line_total,
                    "share_minor": round(share_per_person),
                    "people_count": people_count
                }
                if is_shared:
                    shared_items_detail[person].append(entry)
                else:
                    own_items_detail[person].append(entry)

    total_bill_minor = items_total_minor + int(tax_minor) - int(discount_minor)
    if total_bill_minor < 0:
        raise ValueError(f"Total bill cannot be negative: {total_bill_minor}")

    total_subtotal_float = sum(subtotals_float.values())
    
    # Exact ideal shares as floating point
    exact_shares: Dict[str, float] = {}
    if total_subtotal_float > 0:
        multiplier = total_bill_minor / total_subtotal_float
        for person in member_names:
            exact_shares[person] = subtotals_float[person] * multiplier
    else:
        # If no items or subtotals are 0, split total bill equally among members
        count = len(member_names)
        equal_share = total_bill_minor / count if count > 0 else 0.0
        for person in member_names:
            exact_shares[person] = equal_share

    # Largest Remainder Method (Hare-Niemeyer) for exact integer distribution
    base_shares: Dict[str, int] = {}
    remainders: Dict[str, float] = {}
    for person in member_names:
        share = exact_shares[person]
        base = math.floor(share)
        base_shares[person] = base
        remainders[person] = share - base

    allocated = sum(base_shares.values())
    discrepancy = total_bill_minor - allocated

    # Sort members by remainder descending, tiebreak by original order in member_names
    sorted_by_remainder = sorted(
        member_names,
        key=lambda p: (remainders[p], -member_names.index(p)),
        reverse=True
    )

    final_shares: Dict[str, int] = dict(base_shares)
    for i in range(discrepancy):
        person = sorted_by_remainder[i]
        final_shares[person] += 1

    # Final check
    if sum(final_shares.values()) != total_bill_minor:
        raise ValueError(
            f"Largest remainder method failed: sum of shares {sum(final_shares.values())} != bill total {total_bill_minor}"
        )

    # Detailed breakdown per member
    breakdown: Dict[str, Dict[str, Any]] = {}
    for person in member_names:
        own_sum = sum(e["total_minor"] for e in own_items_detail[person])
        shared_sum = sum(e["share_minor"] for e in shared_items_detail[person])
        raw_subtotal = subtotals_float[person]
        total_m = final_shares[person]
        
        # Tax/discount part is the difference between total and base subtotal
        tax_part = total_m - round(raw_subtotal)
        
        breakdown[person] = {
            "name": person,
            "own_items": own_items_detail[person],
            "own_items_minor": own_sum,
            "shared_items": shared_items_detail[person],
            "shared_part_minor": shared_sum,
            "subtotal_float": raw_subtotal,
            "subtotal_minor": round(raw_subtotal),
            "tax_part_minor": tax_part,
            "total_minor": total_m
        }

    return {
        "items_total_minor": items_total_minor,
        "tax_minor": int(tax_minor),
        "discount_minor": int(discount_minor),
        "total_minor": total_bill_minor,
        "shares": final_shares,
        "breakdown": breakdown
    }
