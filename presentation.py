"""Natural-language display of DB-backed plans; no model calls or JSON output."""
from collections import Counter

from schemas import PLAN_SCHEMA, validate
from tool_calling_function import FOOD_DB, check_plan, compute_plan


MEALS = {"breakfast": "아침", "lunch": "점심", "dinner": "저녁",
         "snack": "간식", "brunch": "브런치"}


def number(value):
    return f"{value:,.1f}".rstrip("0").rstrip(".")


def food_names(codes):
    return ", ".join(FOOD_DB[code]["name"] + (f" {count}인분" if count > 1 else "")
                     for code, count in Counter(codes).items())


def slot_label(slot, multiple_days):
    day, meal = slot.split("_", 1)
    label = MEALS.get(meal, meal)
    return f"{int(day[3:])}일차 {label}" if multiple_days else label


def render_plan(plan, *, previous_plan=None, user_constraint=None):
    validate(plan, PLAN_SCHEMA)
    totals = compute_plan(plan)
    if totals["unknown_codes"]:
        raise ValueError("표시할 식단에 DB 에 없는 음식이 있습니다.")
    days = sorted(totals["days"], key=lambda d: int(d[3:]))
    multiple_days = len(days) > 1
    constraints = user_constraint["constraints"] if user_constraint else None
    checked = bool(user_constraint and check_plan(plan, user_constraint)["passed"])
    lines = []
    if previous_plan:
        kept = [s for s in plan if s in previous_plan and sorted(plan[s]) == sorted(previous_plan[s])]
        changed = [s for s in plan if s in previous_plan and sorted(plan[s]) != sorted(previous_plan[s])]
        if len(kept) == 1:
            slot = kept[0]
            lines.append(f"{slot_label(slot, multiple_days)} 메뉴는 {food_names(plan[slot])} 그대로 유지했어요.")
        if len(changed) == 1:
            slot = changed[0]
            lines.append(f"{slot_label(slot, multiple_days)} 메뉴는 {food_names(previous_plan[slot])} 대신 "
                         f"{food_names(plan[slot])}입니다.")
        if not lines:
            lines.append("기존 식단을 유지했어요." if plan == previous_plan else "말씀하신 수정 사항을 반영했어요.")
    else:
        lines.append("다음과 같이 식단을 추천해 드릴게요.")

    show_protein = bool(constraints and any(v is not None for v in
                        constraints["nutrition"]["per_meal"]["protein_g"].values()))
    show_sodium = bool(constraints and any(v is not None for v in
                       constraints["nutrition"]["per_day"]["sodium_mg"].values()))
    for day in days:
        lines.append("")
        if multiple_days:
            lines.append(f"{int(day[3:])}일차")
        slots = [s for s in plan if s.split("_", 1)[0] == day]
        slots.sort(key=lambda s: list(MEALS).index(s.split("_", 1)[1])
                   if s.split("_", 1)[1] in MEALS else len(MEALS))
        for slot in slots:
            values = totals["slots"][slot]
            detail = f"가격은 {number(values['price_krw'])}원, 열량은 {number(values['kcal'])}kcal예요."
            if show_protein:
                detail += f" 단백질은 {number(values['protein_g'])}g이에요."
            lines.append(f"- {slot_label(slot, False)} 메뉴는 {food_names(plan[slot])}입니다. {detail}")
        if show_sodium:
            sodium = constraints["nutrition"]["per_day"]["sodium_mg"]
            line = f"두 끼의 나트륨 합계는 {number(totals['days'][day]['sodium_mg'])}mg이에요."
            if len(slots) != 2:
                line = line.replace("두 끼의", "이날 식단의")
            if checked and sodium["max"] is not None:
                line += f" 요청하신 하루 {number(sodium['max'])}mg 이하 조건을 충족해요."
            lines.append(line)

    lines.append("")
    total = totals["total"]["price_krw"]
    budget = constraints["budget_krw"]["total_max"] if constraints else None
    if checked and budget is not None:
        lines.append(f"총 식비는 {number(total)}원으로, 요청하신 예산 {number(budget)}원 이내예요.")
    else:
        lines.append(f"총 식비는 {number(total)}원이에요.")
    if checked:
        if constraints["excluded_allergens"]:
            allergens = ", ".join(constraints["excluded_allergens"])
            lines.append(f"DB에서 {allergens} 표시가 있는 메뉴는 제외했어요.")
        if constraints["excluded_tags"]:
            tags = ", ".join(constraints["excluded_tags"])
            lines.append(f"{tags} 표시가 있는 메뉴도 제외했어요.")
    return "\n".join(lines)
