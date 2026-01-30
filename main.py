from fastapi import FastAPI

app = FastAPI()

@app.get("/health")
def health():
    return {"status": "ok"}

from fastapi import FastAPI
from pydantic import BaseModel
from typing import List
import uuid

app = FastAPI()

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
    return {
        "order_id": order_id,
        "status": "CREATED",
        "machine_id": req.machine_id,
        "items": [i.model_dump() for i in req.items],
        "amount_cents": req.amount_cents
    }

