from fastapi import APIRouter, Response, status

from app.deps import CurrentUser, DbDep
from app.schemas.rules import EnabledIn, RuleIn, RuleOut, RuleTestOut
from app.services import rules as service

router = APIRouter(tags=["rules"])


@router.get("/rules", response_model=list[RuleOut])
async def list_rules(user: CurrentUser, db: DbDep):
    return await service.list_rules(db, user)


@router.post("/rules", response_model=RuleOut, status_code=status.HTTP_201_CREATED)
async def create_rule(data: RuleIn, user: CurrentUser, db: DbDep, response: Response):
    created = await service.create(db, user, data)
    response.headers["Location"] = f"/api/rules/{created.id}"
    return created


@router.patch("/rules/{rule_id}", response_model=RuleOut)
async def update_rule(rule_id: int, data: RuleIn, user: CurrentUser, db: DbDep):
    return await service.update(db, user, rule_id, data)


@router.delete("/rules/{rule_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_rule(rule_id: int, user: CurrentUser, db: DbDep):
    await service.remove(db, user, rule_id)


@router.put("/rules/{rule_id}/enabled", response_model=RuleOut)
async def set_enabled(rule_id: int, data: EnabledIn, user: CurrentUser, db: DbDep):
    return await service.set_enabled(db, user, rule_id, data.enabled)


@router.post("/rules/{rule_id}/test", response_model=RuleTestOut)
async def test_rule(rule_id: int, target_id: int, user: CurrentUser, db: DbDep):
    return await service.test(db, user, rule_id, target_id)
