from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from typing import List
import uuid
from datetime import datetime, timezone
from google.cloud.firestore import SERVER_TIMESTAMP
from fastapi import Header
import os
import stripe
from google.cloud import firestore


app = FastAPI()
db = firestore.Client()

stripe.api_key = os.getenv("STRIPE_SECRET_KEY")

@app.post("/orders/{order_id}/start_payment")
def start_payment(order_id: str):
    order_ref = db.collection("orders").document(order_id)
    snap = order_ref.get()
    if not snap.exists:
        raise HTTPException(status_code=404, detail="Order not found")

    order = snap.to_dict() or {}
    if order.get("status") not in ["CREATED", "PAYMENT_STARTED"]:
        raise HTTPException(status_code=400, detail=f"Order not payable from status {order.get('status')}")

    machine_id = order.get("machine_id")
    machine_snap = db.collection("machines").document(machine_id).get()
    if not machine_snap.exists:
        raise HTTPException(status_code=400, detail="Machine not found")

    machine = machine_snap.to_dict() or {}
    reader_id = machine.get("stripe_reader_id")
    if not reader_id:
        raise HTTPException(status_code=400, detail="Machine missing stripe_reader_id")

    # 1) Create PaymentIntent (server-driven Terminal flow)
    pi = stripe.PaymentIntent.create(
        amount=int(order["amount_cents"]),
        currency="usd",
        payment_method_types=["card_present"],
        capture_method="automatic",
        metadata={
            "order_id": order_id,
            "machine_id": machine_id,
        },
    )  # docs: PaymentIntent.create :contentReference[oaicite:2]{index=2}

    # 2) Tell the reader to process this PaymentIntent
    stripe.terminal.Reader.process_payment_intent(
        reader_id,
        payment_intent=pi["id"],
    )  # docs: readers.process_payment_intent :contentReference[oaicite:3]{index=3}

    # Update order status
    order_ref.update({
        "status": "PAYMENT_STARTED",
        "stripe_payment_intent_id": pi["id"],
        "updated_at": SERVER_TIMESTAMP,
    })

    return {"order_id": order_id, "status": "PAYMENT_STARTED", "payment_intent_id": pi["id"]}
@app.get("/health")
def health():
    return {"status": "ok"}

class OrderItem(BaseModel):
    slot_id: str
    qty: int

class CreateOrderRequest(BaseModel):
    machine_id: str
    items: List[OrderItem]
    amount_cents: int

@app.post("/orders")
def create_order(req: CreateOrderRequest):
    order_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc)

    doc = {
        "order_id": order_id,
        "machine_id": req.machine_id,
        "items": [i.model_dump() for i in req.items],
        "amount_cents": req.amount_cents,
        "status": "CREATED",
        "created_at": now,
        "updated_at": now,
    }

    db.collection("orders").document(order_id).set(doc)

    return {
        **doc,
        "created_at": now.isoformat(),
        "updated_at": now.isoformat(),
    }

@app.get("/orders/{order_id}")
def get_order(order_id: str):
    snap = db.collection("orders").document(order_id).get()
    if not snap.exists:
        raise HTTPException(status_code=404, detail="Order not found")

    data = snap.to_dict() or {}
    for k in ["created_at", "updated_at"]:
        v = data.get(k)
        if hasattr(v, "isoformat"):
            data[k] = v.isoformat()

    return data

@app.post("/orders/{order_id}/authorize")
def authorize_order(order_id: str):
    order_ref = db.collection("orders").document(order_id)
    snap = order_ref.get()

    if not snap.exists:
        raise HTTPException(status_code=404, detail="Order not found")

    order = snap.to_dict() or {}

    # Allow idempotent re-calls
    if order.get("status") not in ["CREATED", "AUTHORIZED"]:
        raise HTTPException(status_code=400, detail=f"Order not authorizable from status {order.get('status')}")

    # Update order status
    order_ref.update({
        "status": "AUTHORIZED",
        "updated_at": SERVER_TIMESTAMP,
    })

    machine_id = order.get("machine_id")
    if not machine_id:
        raise HTTPException(status_code=400, detail="Order missing machine_id")

    # Create a vend command
    cmd_ref = (
        db.collection("machines")
          .document(machine_id)
          .collection("commands")
          .document()
    )

    cmd_ref.set({
        "type": "VEND_ORDER",
        "order_id": order_id,
        "machine_id": machine_id,
        "items": order.get("items", []),
        "status": "PENDING",
        "created_at": SERVER_TIMESTAMP,
    })

    return {"status": "AUTHORIZED", "order_id": order_id, "command_id": cmd_ref.id}

@app.get("/machines/{machine_id}/commands/next")
def get_next_command(machine_id: str):
    col = (
        db.collection("machines")
          .document(machine_id)
          .collection("commands")
    )

    snaps = list(col.limit(20).stream())

    for snap in snaps:
        data = snap.to_dict() or {}
        if data.get("status") == "PENDING":
            snap.reference.update({"status": "CLAIMED"})
            data["command_id"] = snap.id
            return data

    return {"status": "NO_COMMAND"}


