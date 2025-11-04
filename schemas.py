"""
Database Schemas for LoanLens AI

Each Pydantic model corresponds to a MongoDB collection. The collection name is the
lowercased class name.
"""

from pydantic import BaseModel, Field
from typing import Optional, List, Dict, Any

class Session(BaseModel):
    """
    Conversation session state for a single customer.
    Collection: "session"
    """
    stage: str = Field("intro", description="Current stage: intro|verification|underwriting|sanction|complete")
    customer_name: Optional[str] = Field(None, description="Customer's name")
    monthly_income: Optional[int] = Field(None, ge=0, description="Declared monthly income in INR")
    requested_amount: Optional[int] = Field(None, ge=0, description="Requested loan amount in INR")
    kyc: Dict[str, Any] = Field(default_factory=dict, description="KYC status and metadata")
    offer: Dict[str, Any] = Field(default_factory=dict, description="Generated offer details, if any")
    messages: List[Dict[str, Any]] = Field(default_factory=list, description="Chat transcript")

class Message(BaseModel):
    """
    Single message in a session.
    Collection: "message"
    """
    session_id: str = Field(...)
    role: str = Field(..., description="user|assistant|system|agent")
    content: str = Field(...)

class Application(BaseModel):
    """
    Loan application data for underwriting and sanction.
    Collection: "application"
    """
    session_id: str = Field(...)
    customer_name: str = Field(...)
    monthly_income: int = Field(..., ge=0)
    requested_amount: int = Field(..., ge=0)
    eligibility_amount: Optional[int] = Field(None, ge=0)
    status: str = Field("pending", description="pending|approved|rejected|sanctioned")
