"""
Architectural Boundary Test — Proves consumer does NOT import or depend on database internals.
"""
import sys
import inspect
from services import masterdb_test_consumer


def test_consumer_has_no_database_dependencies():
    consumer_module = sys.modules[masterdb_test_consumer.__name__]
    source_code = inspect.getsource(consumer_module)

    # Architectural assertions: consumer must not import database OR model files
    assert "sqlalchemy" not in source_code.lower()
    assert "import database" not in source_code.lower()
    assert "from database" not in source_code.lower()
    assert "sqlite" not in source_code.lower()
    assert "postgresql" not in source_code.lower()
    assert "from models import" not in source_code
    assert "import models" not in source_code
    assert "BaseModel" not in source_code  # Uses pure HTTP requests / JSON dicts

    # Verify consumer class relies on standard HTTP client interface
    from services.masterdb_test_consumer import MasterDBTestConsumer
    consumer = MasterDBTestConsumer()
    assert hasattr(consumer, "discover_capabilities")
    assert hasattr(consumer, "get_capability_contract")
    assert hasattr(consumer, "request_access")
    assert hasattr(consumer, "retrieve_capability_data")
