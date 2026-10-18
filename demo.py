"""
demo.py — SecureGuard Conveyor Demonstration Script (Keycloak Authenticated)
"""

import os
os.environ["SECUREGUARD_TEST_MODE"] = "1"

from fastapi.testclient import TestClient
from main import app, pipeline
import persistence
from keycloak_client import create_test_token
from state_machine import AuthState


def reset_db():
    pipeline.state_store._subsystems.clear()
    if persistence.DB_PATH.exists():
        try:
            os.remove(persistence.DB_PATH)
        except OSError:
            pass
    persistence.init_db()


client = TestClient(app)


def run_scenario(
    name: str,
    subsystem_id: str,
    command: dict,
    observed: dict = None,
    auth_roles: list[str] = None,
    mfa_verified: bool = False,
    username: str = "operator01",
    include_auth: bool = True,
):
    print("=" * 65)
    print(f"SCENARIO: {name}")
    print("=" * 65)

    headers = {}
    if include_auth:
        roles = auth_roles if auth_roles is not None else ["operator"]
        token = create_test_token(username=username, roles=roles, mfa_verified=mfa_verified)
        headers = {"Authorization": f"Bearer {token}"}
        print(f"Identity: {username} | Roles: {roles} | MFA (OTP): {'YES' if mfa_verified else 'NO'}")
    else:
        print("Identity: [UNAUTHENTICATED - NO TOKEN]")

    payload = {
        "subsystem_id": subsystem_id,
        "from_speed_rpm": command.get("from_speed_rpm", 0),
        "to_speed_rpm": command.get("to_speed_rpm", 500),
    }

    if observed:
        payload["observed"] = observed

    print(f"Command: SET_SPEED = {payload['to_speed_rpm']} RPM (from {payload['from_speed_rpm']} RPM)")

    resp = client.post("/command", json=payload, headers=headers)

    if resp.status_code != 200:
        print(f"\nDecision: [REJECTED] (HTTP {resp.status_code})")
        print(f"Reason: {resp.json().get('detail', 'Unauthorized')}")
        print("-" * 65 + "\n")
        return {
            "name": name,
            "accepted": False,
            "risk_level": "N/A",
            "new_state": "N/A",
            "decision": f"BLOCKED (HTTP {resp.status_code})",
        }

    data = resp.json()

    if data.get("predicted"):
        print("\nDigital Twin Prediction:")
        print(f"  Current:     {data['predicted'].get('motor_current_amps')} A")
        print(f"  Speed:       {data['predicted'].get('motor_speed_rpm')} RPM")
        print(f"  Temperature: {data['predicted'].get('temperature_c')} C")
        print(f"  Box Rate:    {data['predicted'].get('box_rate_per_min')} boxes/min")

    if data.get("observed"):
        print("\nObserved Sensor Telemetry:")
        print(f"  Current:     {data['observed'].get('motor_current_amps')} A")
        print(f"  Speed:       {data['observed'].get('motor_speed_rpm')} RPM")
        print(f"  Temperature: {data['observed'].get('temperature_c')} C")
        print(f"  Box Rate:    {data['observed'].get('box_rate_per_min')} boxes/min")

    print("\nGovernance Analysis:")
    if data.get("residual") is not None:
        print(f"  Residual:    {data['residual']:.3f}")
    if data.get("risk_score") is not None:
        print(f"  Risk Score:  {data['risk_score']:.1f} / 100")
    if data.get("risk_level") is not None:
        print(f"  Risk Level:  {data['risk_level']}")

    print("\nDecision & State:")
    if data["accepted"]:
        print(f"  Decision:   [ACCEPTED] ({data['reason']})")
        print(f"  New State:  {data.get('new_state', 'NORMAL')}")
    else:
        print("  Decision:   [REJECTED]")
        if data.get("safety_violations"):
            print("  Person 2 Auth Check:   PASSED (Token & Roles Valid)")
            print("  Person 3 Safety Check: FAILED (Physics Violation)")
            print(f"  Violation:             {data['safety_violations'][0]}")
        else:
            print(f"  Reason:                {data.get('reason')}")
        print(f"  State:                 {data.get('new_state', 'UNCHANGED')}")

    if data.get("explanation"):
        print(f"\nXAI Causal Attribution:\n  {data['explanation']}")

    print("-" * 65 + "\n")
    return {
        "name": name,
        "accepted": data["accepted"],
        "risk_level": str(data.get("risk_level") or "N/A"),
        "new_state": str(data.get("new_state") or "N/A"),
        "decision": "ACCEPTED" if data["accepted"] else "REJECTED",
    }


if __name__ == "__main__":
    reset_db()

    print("\n" + "=" * 65)
    print("SECUREGUARD CONVEYOR GOVERNANCE DEMONSTRATION")
    print("Keycloak Identity + Physical Twin + Safety Envelope + Residuals")
    print("=" * 65 + "\n")

    results = []

    # 1. NORMAL OPERATION
    results.append(run_scenario(
        "1 -- NORMAL OPERATION",
        "conv_1",
        {"to_speed_rpm": 500},
        {
            "conveyor_state": "RUNNING",
            "motor_speed_rpm": 500.0,
            "motor_current_amps": 3.0,
            "temperature_c": 40.0,
            "box_rate_per_min": 20.0,
        },
        username="operator01",
        auth_roles=["operator"],
    ))

    # 2. HIGH MOTOR CURRENT (Mechanical Anomaly)
    results.append(run_scenario(
        "2 -- HIGH MOTOR CURRENT ANOMALY",
        "conv_2",
        {"from_speed_rpm": 500, "to_speed_rpm": 900},
        {
            "conveyor_state": "RUNNING",
            "motor_speed_rpm": 640.0,
            "motor_current_amps": 8.7,
            "temperature_c": 48.0,
            "box_rate_per_min": 15.0,
        },
        username="operator01",
        auth_roles=["operator"],
    ))

    # 3. HIGH TEMPERATURE
    results.append(run_scenario(
        "3 -- HIGH TEMPERATURE ANOMALY",
        "conv_3",
        {"to_speed_rpm": 500},
        {
            "conveyor_state": "RUNNING",
            "motor_speed_rpm": 500.0,
            "motor_current_amps": 4.5,
            "temperature_c": 70.0,
            "box_rate_per_min": 20.0,
        },
        username="operator01",
        auth_roles=["operator"],
    ))

    # 4. CONVEYOR STATE MISMATCH (Belt Jam / Motor stopped)
    results.append(run_scenario(
        "4 -- CONVEYOR STATE MISMATCH",
        "conv_4",
        {"to_speed_rpm": 500},
        {
            "conveyor_state": "STOPPED",
            "motor_speed_rpm": 0.0,
            "motor_current_amps": 0.0,
            "temperature_c": 35.0,
            "box_rate_per_min": 0.0,
        },
        username="operator01",
        auth_roles=["operator"],
    ))

    # 5. UNSAFE SPEED COMMAND (Operator issues 1200 RPM - Exceeds 1000 limit)
    results.append(run_scenario(
        "5 -- UNSAFE SPEED (Authorized != Safe)",
        "conv_5",
        {"to_speed_rpm": 1200},
        username="operator01",
        auth_roles=["operator"],
    ))

    # 6. PRIVILEGED BUT UNSAFE (Supervisor with OTP issues 1500 RPM)
    results.append(run_scenario(
        "6 -- SUPERVISOR WITH MFA BUT UNSAFE",
        "conv_6",
        {"to_speed_rpm": 1500},
        username="supervisor01",
        auth_roles=["supervisor"],
        mfa_verified=True,
    ))

    # 7. CYBER ATTACK: UNCREDENTIALED INTRUDER
    results.append(run_scenario(
        "7 -- UNCREDENTIALED INTRUDER ATTACK",
        "conv_7",
        {"to_speed_rpm": 500},
        include_auth=False,
    ))

    # 8. PRIVILEGE ESCALATION: OPERATOR LACKING MFA ON DEGRADED SUBSYSTEM
    conv_sub = pipeline.state_store.get("conv_8")
    conv_sub.state = AuthState.DEGRADED
    results.append(run_scenario(
        "8 -- DEGRADED STATE (No MFA Step-Up)",
        "conv_8",
        {"to_speed_rpm": 500},
        username="operator01",
        auth_roles=["operator"],
        mfa_verified=False,
    ))

    print("\n" + "=" * 75)
    print("DEMONSTRATION SUMMARY")
    print("=" * 75)
    print(f"{'Scenario':<40} | {'Decision':<10} | {'Risk':<10} | {'State':<12}")
    print("-" * 75)
    for res in results:
        print(f"{res['name']:<40} | {res['decision']:<10} | {res['risk_level']:<10} | {res['new_state']:<12}")
    print("=" * 75 + "\n")
