"""
End-to-End Test for MASTERDB_TEST_CONSUMER and Representative Application Consumers (FIN, Bharat Mala, Marine).
"""
from fastapi.testclient import TestClient
import main
from services.masterdb_test_consumer import MasterDBTestConsumer


def test_masterdb_test_consumer_full_10_step_flow():
    client = TestClient(main.app)
    consumer = MasterDBTestConsumer(client=client, application_id="MASTERDB_TEST_CONSUMER")
    result = consumer.run_full_flow(capability_id="cap-mangrove-monitoring", purpose="environmental_monitoring")
    
    assert result["status"] == "SUCCESS"
    assert result["token"] is not None
    assert result["capabilities_count"] >= 4
    assert result["contract"]["capability_id"] == "cap-mangrove-monitoring"
    assert result["grant"]["authorized"] is True
    assert result["data_response"]["capability"]["capability_id"] == "cap-mangrove-monitoring"
    assert "provenance" in result["data_response"]


def test_existing_consumers_fin_bharat_mala_marine():
    # Prove FIN, Bharat Mala, and Marine use the exact SAME capability access contract
    client = TestClient(main.app)
    consumers = [
        ("FIN", "cap-fin-market-analytics", "financial_analysis"),
        ("Bharat Mala", "cap-bharat-mala-highways", "infrastructure_planning"),
        ("Marine", "cap-maritime-cargo", "maritime_logistics"),
    ]

    for app_id, cap_id, purpose in consumers:
        consumer = MasterDBTestConsumer(client=client, application_id=app_id)
        result = consumer.run_full_flow(capability_id=cap_id, purpose=purpose)
        assert result["status"] == "SUCCESS"
        assert result["grant"]["authorized"] is True
        assert result["data_response"]["capability"]["capability_id"] == cap_id
        assert "provenance" in result["data_response"]
