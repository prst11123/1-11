"""External transaction port and complete DEMO implementation.

In v1 the adapter NEVER connects to a wallet, sends Stars or transfers NFTs.
A future verified Telegram transaction integration must be separately audited and
installed through dependency injection; it cannot be activated by an env variable.
"""
from typing import Protocol
from dataclasses import dataclass


@dataclass(frozen=True)
class TransferDecision:
    mode: str
    external_transaction_performed: bool


class TransferGateway(Protocol):
    async def validate_transfer_request(self, offer, actor_id: int) -> TransferDecision: ...


class DemoTransferGateway:
    async def validate_transfer_request(self, offer, actor_id: int) -> TransferDecision:
        if offer.status != "accepted" or offer.recipient_user_id != actor_id:
            raise ValueError("Demo-передача доступна только получателю принятого предложения")
        return TransferDecision(mode="demo", external_transaction_performed=False)
