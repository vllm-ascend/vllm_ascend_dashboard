"""告警规则 API（条件组模型）"""

from fastapi import APIRouter, HTTPException, Query, status
from sqlalchemy import select

from app.api.deps import CurrentUser, DbSession
from app.models import AlertCondition, AlertConditionGroup, AlertHistory as AlertHistoryModel, AlertRule
from app.schemas import (
    AlertConditionCreate,
    AlertConditionResponse,
    AlertConditionGroupCreate,
    AlertConditionGroupResponse,
    AlertHistoryResponse,
    AlertRuleCreate,
    AlertRuleResponse,
    AlertRuleUpdate,
)

router = APIRouter()

VALID_METRIC_FIELDS = [
    "npu_utilization", "npu_total", "npu_used", "npu_available",
    "executing_pods_count", "pr_count",
    "cpu_utilization", "memory_utilization",
    "cpu_cores_used", "cpu_cores_total",
    "memory_bytes_used", "memory_bytes_total",
]
VALID_OPERATORS = [">", "<", ">=", "<=", "=="]


def _validate_condition(c: AlertConditionCreate):
    if c.metric_field not in VALID_METRIC_FIELDS:
        raise HTTPException(400, f"无效 metric_field: {c.metric_field}")
    if c.operator not in VALID_OPERATORS:
        raise HTTPException(400, f"无效 operator: {c.operator}")
    if c.threshold is None:
        raise HTTPException(400, "threshold 不能为空")


async def _build_rule_response(db, rule: AlertRule) -> AlertRuleResponse:
    g_stmt = select(AlertConditionGroup).where(AlertConditionGroup.rule_id == rule.id).order_by(AlertConditionGroup.display_order)
    g_result = await db.execute(g_stmt)
    groups = list(g_result.scalars().all())

    group_responses = []
    for g in groups:
        c_stmt = select(AlertCondition).where(AlertCondition.group_id == g.id).order_by(AlertCondition.display_order)
        c_result = await db.execute(c_stmt)
        conditions = [AlertConditionResponse.model_validate(c) for c in c_result.scalars().all()]
        group_responses.append(AlertConditionGroupResponse(
            id=g.id, rule_id=g.rule_id, logic=g.logic, display_order=g.display_order,
            conditions=conditions,
        ))

    resp = AlertRuleResponse.model_validate(rule)
    resp.groups = group_responses
    return resp


async def _delete_groups_and_conditions(db, rule_id: int):
    groups = (await db.execute(select(AlertConditionGroup).where(AlertConditionGroup.rule_id == rule_id))).scalars().all()
    for g in groups:
        await db.execute(select(AlertCondition).where(AlertCondition.group_id == g.id))  # no-op, just import
        # Delete conditions
        from sqlalchemy import delete
        await db.execute(delete(AlertCondition).where(AlertCondition.group_id == g.id))
    from sqlalchemy import delete
    await db.execute(delete(AlertConditionGroup).where(AlertConditionGroup.rule_id == rule_id))


async def _create_groups_and_conditions(db, rule_id: int, groups: list[AlertConditionGroupCreate]):
    for idx, gc in enumerate(groups):
        g = AlertConditionGroup(rule_id=rule_id, logic=gc.logic.upper() if gc.logic else "AND", display_order=idx)
        db.add(g)
        await db.flush()
        for cdx, cc in enumerate(gc.conditions):
            _validate_condition(cc)
            c = AlertCondition(
                group_id=g.id, metric_field=cc.metric_field, operator=cc.operator,
                threshold=cc.threshold, is_exclude=cc.is_exclude, display_order=cdx,
            )
            db.add(c)


# ── Endpoints ──

@router.get("/alert-rules", response_model=list[AlertRuleResponse])
async def list_alert_rules(db: DbSession, current_user: CurrentUser):
    stmt = select(AlertRule)
    if current_user.role not in ("admin", "super_admin"):
        stmt = stmt.where(AlertRule.user_id == current_user.id)
    stmt = stmt.order_by(AlertRule.created_at.desc())
    result = await db.execute(stmt)
    rules = list(result.scalars().all())
    return [await _build_rule_response(db, r) for r in rules]


@router.get("/alert-rules/{rule_id}", response_model=AlertRuleResponse)
async def get_alert_rule(db: DbSession, rule_id: int, current_user: CurrentUser):
    rule = await _get_rule(db, rule_id, current_user)
    return await _build_rule_response(db, rule)


@router.post("/alert-rules", response_model=AlertRuleResponse, status_code=201)
async def create_alert_rule(db: DbSession, data: AlertRuleCreate, current_user: CurrentUser):
    if not data.groups or sum(len(g.conditions) for g in data.groups) == 0:
        raise HTTPException(400, "至少需要一个条件")

    rule = AlertRule(
        user_id=current_user.id, name=data.name,
        cluster_id=data.cluster_id, node_name=data.node_name,
        enabled=data.enabled, notify_email=data.notify_email,
        notification_email=data.notification_email,
    )
    db.add(rule)
    await db.flush()

    await _create_groups_and_conditions(db, rule.id, data.groups)
    await db.commit()
    await db.refresh(rule)
    return await _build_rule_response(db, rule)


@router.put("/alert-rules/{rule_id}", response_model=AlertRuleResponse)
async def update_alert_rule(db: DbSession, rule_id: int, data: AlertRuleUpdate, current_user: CurrentUser):
    rule = await _get_rule(db, rule_id, current_user)
    update_data = data.model_dump(exclude_unset=True)
    groups_data = update_data.pop("groups", None)

    for field, value in update_data.items():
        setattr(rule, field, value)

    if groups_data is not None:
        await _delete_groups_and_conditions(db, rule.id)
        await _create_groups_and_conditions(db, rule.id, groups_data)

    await db.commit()
    await db.refresh(rule)
    return await _build_rule_response(db, rule)


@router.delete("/alert-rules/{rule_id}")
async def delete_alert_rule(db: DbSession, rule_id: int, current_user: CurrentUser):
    rule = await _get_rule(db, rule_id, current_user)
    await _delete_groups_and_conditions(db, rule.id)
    await db.delete(rule)
    await db.commit()
    return {"message": "告警规则已删除"}


@router.get("/alert-rules/{rule_id}/history", response_model=list[AlertHistoryResponse])
async def get_alert_rule_history(db: DbSession, rule_id: int, current_user: CurrentUser, limit: int = Query(50, ge=1, le=500)):
    await _get_rule(db, rule_id, current_user)
    stmt = select(AlertHistoryModel).where(AlertHistoryModel.rule_id == rule_id).order_by(AlertHistoryModel.triggered_at.desc()).limit(limit)
    result = await db.execute(stmt)
    return [AlertHistoryResponse.model_validate(h) for h in result.scalars().all()]


@router.get("/alert-rules-history", response_model=list[AlertHistoryResponse])
async def get_all_alert_history(db: DbSession, current_user: CurrentUser, limit: int = Query(50, ge=1, le=500)):
    stmt = select(AlertHistoryModel).join(AlertRule, AlertHistoryModel.rule_id == AlertRule.id).order_by(AlertHistoryModel.triggered_at.desc()).limit(limit)
    if current_user.role not in ("admin", "super_admin"):
        stmt = stmt.where(AlertRule.user_id == current_user.id)
    result = await db.execute(stmt)
    return [AlertHistoryResponse.model_validate(h) for h in result.scalars().all()]


async def _get_rule(db, rule_id: int, current_user: CurrentUser) -> AlertRule:
    rule = (await db.execute(select(AlertRule).where(AlertRule.id == rule_id))).scalar_one_or_none()
    if not rule:
        raise HTTPException(404, "告警规则不存在")
    if current_user.role not in ("admin", "super_admin") and rule.user_id != current_user.id:
        raise HTTPException(403, "无权限")
    return rule
