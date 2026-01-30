from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from typing import List
import uuid
from datetime import datetime, timezone
from google.cloud.firestore import SERVER_TIMESTAMP

from google.cloud import firestore

app = FastAPI()
db = firestore.Client()

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

    order = snap.to_dict()

    if order.get("status") != "CREATED":
        raise HTTPException(status_code=400, detail="Order not in CREATED state")

    # Update order status
    order_ref.update({
        "status": "AUTHORIZED",
        "updated_at": SERVER_TIMESTAMP,
    })

    machine_id = order["machine_id"]

    # Create vend command for the machine
    cmd_ref = (
        db.collection("machines")
          .document(machine_id)
          .collection("commands")
          .document()
    )

    cmd_ref.set({
        "type": "VEND_ORDER",
        "order_id": order_id,
        "items": order["items"],
        "status": "PENDING",
        "created_at": SERVER_TIMESTAMP,
    })

    return {"status": "AUTHORIZED", "order_id": order_id}

@app.get("/machines/{machine_id}/commands/next")
def get_next_command(machine_id: str):
    cmds = (
        db.collection("machines")
          .document(machine_id)
          .collection("commands")
          .where("status", "==", "PENDING")
          .limit(1)
          .stream()
    )

    for cmd in cmds:
        cmd.reference.update({"status": "CLAIMED"})
        data = cmd.to_dict()
        data["command_id"] = cmd.id
        return data

    return {"status": "NO_COMMAND"}

