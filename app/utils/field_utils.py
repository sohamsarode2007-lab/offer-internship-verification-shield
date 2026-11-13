"""
Field Unwrap Utility
Provides a standardized helper to safely unwrap candidate fields from extracted facts dictionaries.
Prevents leaking structured dict objects ({'value': ..., 'confidence': ..., 'status': ...}) into strings,
DNS lookups, or user-facing output.
"""
from typing import Any, Optional


def get_field_value(data: Optional[Any], *keys: str) -> Optional[str]:
    """
    Safely unwrap a field value from data.
    
    `data` can be:
      - a plain string or primitive
      - a facts dictionary containing candidate keys
      - a structured dict like {'value': ..., 'confidence': ..., 'status': ...}
      
    `keys` are candidate dictionary keys checked in sequence (e.g. 'domain', 'sender_domain').
    
    Returns:
      - Clean non-empty string value if resolved
      - None if missing, failed_extraction, empty, or unresolvable
      - NEVER returns a dict object
    """
    if data is None:
        return None

    # If data itself is already a string/primitive (not a dict)
    if not isinstance(data, dict):
        s = str(data).strip()
        return s if s else None

    # If data is a structured field dict directly, e.g. {'value': 'example.com', ...}
    if "value" in data and ("status" in data or "confidence" in data):
        val = data.get("value")
        if val is None or data.get("status") == "failed_extraction":
            return None
        if isinstance(val, list):
            # If value is a list (e.g. monetary_amounts or account_numbers), return first element or joined string
            non_empty = [str(x).strip() for x in val if x and str(x).strip()]
            return ", ".join(non_empty) if non_empty else None
        s = str(val).strip()
        return s if s else None

    # Iterate over candidate keys if data is a multi-key facts dict
    if not keys:
        return None

    for key in keys:
        if key not in data:
            continue
        field = data[key]
        if field is None:
            continue

        if isinstance(field, dict):
            # Handles {'value': 'val', 'confidence': 0.9, 'status': 'extracted'}
            val = field.get("value")
            status = field.get("status")
            if status == "failed_extraction" or val is None:
                continue
            if isinstance(val, list):
                non_empty = [str(x).strip() for x in val if x and str(x).strip()]
                if non_empty:
                    return ", ".join(non_empty)
                continue
            s = str(val).strip()
            if s and not s.startswith("{'value'"):
                return s
        elif isinstance(field, list):
            non_empty = [str(x).strip() for x in field if x and str(x).strip()]
            if non_empty:
                return ", ".join(non_empty)
        else:
            s = str(field).strip()
            if s and not s.startswith("{'value'"):
                return s

    return None
