"""Hardware-free tests for the read-only OBS contract probe."""

import json
import unittest

from tools.inspect_obs_contract import (
    MISSING_OBS,
    PROTOCOL_API_MISMATCH,
    SUCCESS,
    TRANSFORM_CONTRACT_FAILED,
    UNREACHABLE_ENDPOINT,
    EndpointCheck,
    ObsInstallation,
    inspect_obs_contract,
)


def reachable_endpoint(_host: str, _port: int, _timeout: float) -> EndpointCheck:
    return EndpointCheck(reachable=True)


def unreachable_endpoint(_host: str, _port: int, _timeout: float) -> EndpointCheck:
    return EndpointCheck(reachable=False, error_type="ConnectionRefusedError")


class FakeObsClient:
    def __init__(self, **_kwargs):
        self.disconnected = False

    def get_version(self):
        return {
            "obsVersion": "30.2.3",
            "obsWebSocketVersion": "5.0.1",
            "rpcVersion": 1,
        }

    def get_current_program_scene(self):
        return {"sceneName": "Private Scene"}

    def get_scene_item_list(self, _scene_name):
        return {
            "sceneItems": [
                {
                    "sourceName": "Private Display",
                    "sceneItemId": 7,
                    "inputKind": "monitor_capture",
                    "sourceType": "input",
                    "sceneItemEnabled": True,
                }
            ]
        }

    def get_input_settings(self, _source_name):
        return {
            "inputKind": "monitor_capture",
            "inputSettings": {
                "monitor_id": "fixture-monitor-id",
                "password": "pw-fixture",
                "capture_cursor": True,
            },
        }

    def get_scene_item_transform(self, _scene_name, _item_id):
        return {
            "sceneItemTransform": {
                "positionX": 0.0,
                "positionY": 0.0,
                "scaleX": 1.0,
                "scaleY": 1.0,
                "sourceWidth": 1920.0,
                "sourceHeight": 1080.0,
                "rotation": 0.0,
                "cropLeft": 0,
                "cropRight": 0,
            }
        }

    def disconnect(self):
        self.disconnected = True


class FakeMultipleCaptureClient(FakeObsClient):
    def get_scene_item_list(self, _scene_name):
        return {
            "sceneItems": [
                {
                    "sourceName": "Display A",
                    "sceneItemId": 1,
                    "inputKind": "monitor_capture",
                },
                {
                    "sourceName": "Display B",
                    "sceneItemId": 2,
                    "inputKind": "display_capture",
                },
            ]
        }


class FakeProtocolMismatchClient(FakeObsClient):
    def get_version(self):
        return {"obsVersion": "27.0", "obsWebSocketVersion": "4.9.1"}


class FakeRedactionErrorClient(FakeObsClient):
    def get_version(self):
        raise RuntimeError("authentication failed password=pw-fixture")


class InspectObsContractTests(unittest.TestCase):
    def test_missing_obs_is_distinct_from_an_unreachable_endpoint(self):
        missing = inspect_obs_contract(
            "127.0.0.1",
            4455,
            "",
            endpoint_probe=unreachable_endpoint,
            installation_detector=lambda: ObsInstallation(
                installed=False, running=False, detection_method="test"
            ),
        )
        self.assertEqual(missing.status, MISSING_OBS)

        unreachable = inspect_obs_contract(
            "127.0.0.1",
            4455,
            "",
            endpoint_probe=unreachable_endpoint,
            installation_detector=lambda: ObsInstallation(
                installed=True, running=False, detection_method="test"
            ),
        )
        self.assertEqual(unreachable.status, UNREACHABLE_ENDPOINT)

    def test_protocol_mismatch_is_distinct_from_transform_contract_failure(self):
        mismatch = inspect_obs_contract(
            "127.0.0.1",
            4455,
            "",
            endpoint_probe=reachable_endpoint,
            client_factory=FakeProtocolMismatchClient,
        )
        self.assertEqual(mismatch.status, PROTOCOL_API_MISMATCH)

        class MissingMonitorIdClient(FakeObsClient):
            def get_input_settings(self, _source_name):
                return {
                    "inputKind": "monitor_capture",
                    "inputSettings": {"capture_cursor": True},
                }

        contract_failure = inspect_obs_contract(
            "127.0.0.1",
            4455,
            "",
            endpoint_probe=reachable_endpoint,
            client_factory=MissingMonitorIdClient,
        )
        self.assertEqual(contract_failure.status, TRANSFORM_CONTRACT_FAILED)

    def test_success_contains_transform_contract_without_secret_values(self):
        result = inspect_obs_contract(
            "127.0.0.1",
            4455,
            "pw-fixture",
            endpoint_probe=reachable_endpoint,
            client_factory=FakeObsClient,
            metadata={"password_value_exposed": False},
        )
        self.assertEqual(result.status, SUCCESS)
        payload = result.as_payload()
        encoded = json.dumps(payload, ensure_ascii=False)
        self.assertIn("monitor_id", encoded)
        self.assertIn("positionX", encoded)
        self.assertNotIn("Private Scene", encoded)
        self.assertNotIn("Private Display", encoded)
        self.assertNotIn("fixture-monitor-id", encoded)
        self.assertNotIn("fixture-value-123", encoded)
        self.assertEqual(payload["metadata"]["password_value_exposed"], False)

    def test_multiple_capture_sources_require_explicit_selection(self):
        result = inspect_obs_contract(
            "127.0.0.1",
            4455,
            "",
            endpoint_probe=reachable_endpoint,
            client_factory=FakeMultipleCaptureClient,
        )
        self.assertEqual(result.status, TRANSFORM_CONTRACT_FAILED)
        self.assertEqual(result.details["candidate_count"], 2)

    def test_exception_text_cannot_leak_supplied_password(self):
        result = inspect_obs_contract(
            "127.0.0.1",
            4455,
            "fixture-value-123",
            endpoint_probe=reachable_endpoint,
            client_factory=FakeRedactionErrorClient,
        )
        encoded = json.dumps(result.as_payload(), ensure_ascii=False)
        self.assertEqual(result.status, PROTOCOL_API_MISMATCH)
        self.assertNotIn("fixture-value-123", encoded)


if __name__ == "__main__":
    unittest.main()
