"""Phase 4 (Guma OS) API: automations, AI receptionist, integrations, and the telephony gateway."""

from __future__ import annotations

import hmac
import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Header, status

from app.api.deps import AppSettings, CustomerUser, DbSession, human_only
from app.core.exceptions import AuthenticationError, GumaWebError
from app.domains.automation.rules import PRESETS
from app.domains.billing.entitlements import Feature
from app.models import (
    ApiKey,
    AutomationRule,
    AutomationRun,
    Call,
    Customer,
    VoiceSettings,
    WebhookDelivery,
    WebhookEndpoint,
)
from app.schemas.guma_os import (
    ApiKeyCreate,
    ApiKeyCreated,
    ApiKeyRead,
    AutomationRead,
    AutomationRunRead,
    AutomationUpdate,
    AutomationWrite,
    CallRead,
    DeliveryRead,
    InboundCall,
    PresetRead,
    TestCallIn,
    VoiceSettingsRead,
    VoiceSettingsUpdate,
    VoiceTurnIn,
    VoiceTurnOut,
    WebhookCreate,
    WebhookRead,
    WebhookSecret,
    WebhookUpdate,
)
from app.services.automation_service import AutomationService
from app.services.customer_service import CustomerService
from app.services.entitlements import require_feature
from app.services.integration_service import IntegrationService
from app.services.voice_service import VoiceService

router = APIRouter(prefix="/customer", tags=["Customer Portal: Automations, Receptionist, Integrations"])
gateway = APIRouter(prefix="/voice", tags=["Voice gateway (telephony adapter)"])


def _customer(user, db, settings, feature: Feature) -> Customer:
    customer = CustomerService(db, settings).for_user(user)
    require_feature(db, customer.business_id, feature)
    return customer


# --- Automations ---------------------------------------------------------------------------------
@router.get("/automations", response_model=list[AutomationRead])
def automations(user: CustomerUser, db: DbSession, settings: AppSettings) -> list[AutomationRule]:
    customer = _customer(user, db, settings, Feature.AUTOMATION)
    return list(AutomationService(db, settings).rules(customer.business_id))


@router.get("/automations/presets", response_model=list[PresetRead])
def presets(user: CustomerUser, db: DbSession, settings: AppSettings) -> list[dict]:
    _customer(user, db, settings, Feature.AUTOMATION)
    return PRESETS


@router.post("/automations", response_model=AutomationRead, status_code=status.HTTP_201_CREATED)
def create_automation(body: AutomationWrite, user: CustomerUser, db: DbSession,
                      settings: AppSettings) -> AutomationRule:
    customer = _customer(user, db, settings, Feature.AUTOMATION)
    return AutomationService(db, settings).create(customer.business_id, body.model_dump())


@router.post("/automations/presets/{key}", response_model=AutomationRead, status_code=status.HTTP_201_CREATED)
def install_preset(key: str, user: CustomerUser, db: DbSession, settings: AppSettings) -> AutomationRule:
    customer = _customer(user, db, settings, Feature.AUTOMATION)
    return AutomationService(db, settings).install_preset(customer.business_id, key)


@router.patch("/automations/{rule_id}", response_model=AutomationRead)
def update_automation(rule_id: uuid.UUID, body: AutomationUpdate, user: CustomerUser, db: DbSession,
                      settings: AppSettings) -> AutomationRule:
    customer = _customer(user, db, settings, Feature.AUTOMATION)
    service = AutomationService(db, settings)
    return service.update(service.rule(customer.business_id, rule_id), body.model_dump(exclude_unset=True))


@router.delete("/automations/{rule_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_automation(rule_id: uuid.UUID, user: CustomerUser, db: DbSession, settings: AppSettings) -> None:
    customer = _customer(user, db, settings, Feature.AUTOMATION)
    db.delete(AutomationService(db, settings).rule(customer.business_id, rule_id))
    db.commit()


@router.get("/automations/runs", response_model=list[AutomationRunRead])
def automation_runs(user: CustomerUser, db: DbSession, settings: AppSettings) -> list[AutomationRun]:
    customer = _customer(user, db, settings, Feature.AUTOMATION)
    return list(AutomationService(db, settings).runs(customer.business_id))


# --- AI receptionist -----------------------------------------------------------------------------
@router.get("/voice/settings", response_model=VoiceSettingsRead)
def voice_settings(user: CustomerUser, db: DbSession, settings: AppSettings) -> VoiceSettings:
    customer = _customer(user, db, settings, Feature.VOICE_RECEPTIONIST)
    row = VoiceService(db, settings).settings_for(customer.business_id)
    db.commit()
    return row


@router.put("/voice/settings", response_model=VoiceSettingsRead)
def update_voice_settings(body: VoiceSettingsUpdate, user: CustomerUser, db: DbSession,
                          settings: AppSettings) -> VoiceSettings:
    customer = _customer(user, db, settings, Feature.VOICE_RECEPTIONIST)
    return VoiceService(db, settings).update_settings(customer.business_id, body.model_dump(exclude_unset=True))


@router.post("/voice/test-call", response_model=VoiceTurnOut, status_code=status.HTTP_201_CREATED,
             summary="Start a simulated call (portal tester)")
def test_call(body: TestCallIn, user: CustomerUser, db: DbSession, settings: AppSettings) -> VoiceTurnOut:
    customer = _customer(user, db, settings, Feature.VOICE_RECEPTIONIST)
    call, turn = VoiceService(db, settings).start_test(customer.business_id, body.caller)
    return VoiceTurnOut(call_id=call.id, say=turn.say, action=turn.action.value)


@router.post("/voice/test-call/{call_id}/turn", response_model=VoiceTurnOut)
def test_call_turn(call_id: uuid.UUID, body: VoiceTurnIn, user: CustomerUser, db: DbSession,
                   settings: AppSettings) -> VoiceTurnOut:
    customer = _customer(user, db, settings, Feature.VOICE_RECEPTIONIST)
    service = VoiceService(db, settings)
    call = service.get_call(call_id, customer.business_id)
    turn = service.turn(call, body.text)
    return VoiceTurnOut(call_id=call.id, say=turn.say, action=turn.action.value, transfer_to=turn.transfer_to)


@router.get("/voice/calls", response_model=list[CallRead])
def calls(user: CustomerUser, db: DbSession, settings: AppSettings) -> list[Call]:
    customer = _customer(user, db, settings, Feature.VOICE_RECEPTIONIST)
    return list(VoiceService(db, settings).calls(customer.business_id))


# --- Integrations: API keys + webhooks (login session only) --------------------------------------
@router.get("/integrations/api-keys", response_model=list[ApiKeyRead], dependencies=[Depends(human_only)])
def api_keys(user: CustomerUser, db: DbSession, settings: AppSettings) -> list[ApiKey]:
    customer = _customer(user, db, settings, Feature.INTEGRATIONS)
    return list(IntegrationService(db, settings).api_keys(customer.business_id))


@router.post("/integrations/api-keys", response_model=ApiKeyCreated, status_code=status.HTTP_201_CREATED,
             dependencies=[Depends(human_only)], summary="Create an API key (the key is shown only once)")
def create_api_key(body: ApiKeyCreate, user: CustomerUser, db: DbSession, settings: AppSettings) -> ApiKeyCreated:
    customer = _customer(user, db, settings, Feature.INTEGRATIONS)
    row, key = IntegrationService(db, settings).create_api_key(customer.business_id, user.id, body.name,
                                                                body.read_only)
    return ApiKeyCreated.model_validate({**ApiKeyRead.model_validate(row).model_dump(), "key": key})


@router.delete("/integrations/api-keys/{key_id}", status_code=status.HTTP_204_NO_CONTENT,
               dependencies=[Depends(human_only)])
def revoke_api_key(key_id: uuid.UUID, user: CustomerUser, db: DbSession, settings: AppSettings) -> None:
    customer = _customer(user, db, settings, Feature.INTEGRATIONS)
    IntegrationService(db, settings).revoke_api_key(customer.business_id, key_id)


@router.get("/integrations/webhooks", response_model=list[WebhookRead], dependencies=[Depends(human_only)])
def webhooks(user: CustomerUser, db: DbSession, settings: AppSettings) -> list[WebhookEndpoint]:
    customer = _customer(user, db, settings, Feature.INTEGRATIONS)
    return list(IntegrationService(db, settings).endpoints(customer.business_id))


@router.post("/integrations/webhooks", response_model=WebhookRead, status_code=status.HTTP_201_CREATED,
             dependencies=[Depends(human_only)])
def create_webhook(body: WebhookCreate, user: CustomerUser, db: DbSession, settings: AppSettings) -> WebhookEndpoint:
    customer = _customer(user, db, settings, Feature.INTEGRATIONS)
    return IntegrationService(db, settings).create_endpoint(customer.business_id, body.url, body.events)


@router.patch("/integrations/webhooks/{endpoint_id}", response_model=WebhookRead, dependencies=[Depends(human_only)])
def update_webhook(endpoint_id: uuid.UUID, body: WebhookUpdate, user: CustomerUser, db: DbSession,
                   settings: AppSettings) -> WebhookEndpoint:
    customer = _customer(user, db, settings, Feature.INTEGRATIONS)
    service = IntegrationService(db, settings)
    return service.update_endpoint(service.endpoint(customer.business_id, endpoint_id), body.url, body.events,
                                   body.active)


@router.delete("/integrations/webhooks/{endpoint_id}", status_code=status.HTTP_204_NO_CONTENT,
               dependencies=[Depends(human_only)])
def delete_webhook(endpoint_id: uuid.UUID, user: CustomerUser, db: DbSession, settings: AppSettings) -> None:
    customer = _customer(user, db, settings, Feature.INTEGRATIONS)
    db.delete(IntegrationService(db, settings).endpoint(customer.business_id, endpoint_id))
    db.commit()


@router.get("/integrations/webhooks/{endpoint_id}/secret", response_model=WebhookSecret,
            dependencies=[Depends(human_only)], summary="Signing secret (derived, never stored)")
def webhook_secret(endpoint_id: uuid.UUID, user: CustomerUser, db: DbSession, settings: AppSettings) -> WebhookSecret:
    customer = _customer(user, db, settings, Feature.INTEGRATIONS)
    service = IntegrationService(db, settings)
    return WebhookSecret(secret=service.secret(service.endpoint(customer.business_id, endpoint_id)))


@router.post("/integrations/webhooks/{endpoint_id}/rotate-secret", response_model=WebhookSecret,
             dependencies=[Depends(human_only)])
def rotate_webhook_secret(endpoint_id: uuid.UUID, user: CustomerUser, db: DbSession,
                          settings: AppSettings) -> WebhookSecret:
    customer = _customer(user, db, settings, Feature.INTEGRATIONS)
    service = IntegrationService(db, settings)
    return WebhookSecret(secret=service.rotate_secret(service.endpoint(customer.business_id, endpoint_id)))


@router.post("/integrations/webhooks/{endpoint_id}/test", response_model=DeliveryRead,
             dependencies=[Depends(human_only)], summary="Queue a signed 'ping' delivery")
def test_webhook(endpoint_id: uuid.UUID, user: CustomerUser, db: DbSession, settings: AppSettings) -> WebhookDelivery:
    customer = _customer(user, db, settings, Feature.INTEGRATIONS)
    service = IntegrationService(db, settings)
    return service.send_test(service.endpoint(customer.business_id, endpoint_id))


@router.get("/integrations/deliveries", response_model=list[DeliveryRead], dependencies=[Depends(human_only)])
def deliveries(user: CustomerUser, db: DbSession, settings: AppSettings) -> list[WebhookDelivery]:
    customer = _customer(user, db, settings, Feature.INTEGRATIONS)
    return list(IntegrationService(db, settings).deliveries(customer.business_id))


# --- Telephony gateway (server-to-server) ---------------------------------------------------------
class GatewayDisabled(GumaWebError):
    status_code = 503
    code = "voice_gateway_disabled"


def require_gateway(settings: AppSettings,
                    token: Annotated[str | None, Header(alias="X-Voice-Gateway-Token")] = None) -> None:
    if not settings.voice_gateway_token:
        raise GatewayDisabled("Voice gateway is not configured (VOICE_GATEWAY_TOKEN)")
    if not token or not hmac.compare_digest(token, settings.voice_gateway_token):
        raise AuthenticationError("Invalid voice gateway token")


@gateway.post("/inbound", response_model=VoiceTurnOut, status_code=status.HTTP_201_CREATED,
              dependencies=[Depends(require_gateway)], summary="A call arrived on a receptionist number")
def inbound(body: InboundCall, db: DbSession, settings: AppSettings) -> VoiceTurnOut:
    call, turn = VoiceService(db, settings).inbound(body.to, body.caller)
    return VoiceTurnOut(call_id=call.id, say=turn.say, action=turn.action.value)


@gateway.post("/calls/{call_id}/turn", response_model=VoiceTurnOut, dependencies=[Depends(require_gateway)],
              summary="Caller speech (transcribed by the gateway's ASR) -> what to say next")
def gateway_turn(call_id: uuid.UUID, body: VoiceTurnIn, db: DbSession, settings: AppSettings) -> VoiceTurnOut:
    service = VoiceService(db, settings)
    call = service.get_call(call_id)
    turn = service.turn(call, body.text)
    return VoiceTurnOut(call_id=call.id, say=turn.say, action=turn.action.value, transfer_to=turn.transfer_to)


@gateway.post("/calls/{call_id}/end", response_model=CallRead, dependencies=[Depends(require_gateway)],
              summary="Caller hung up")
def gateway_end(call_id: uuid.UUID, db: DbSession, settings: AppSettings) -> Call:
    service = VoiceService(db, settings)
    return service.end(service.get_call(call_id))
