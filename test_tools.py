"""Quick smoke test for tools.py against the real Open Dental database."""

import asyncio
from dotenv import load_dotenv

load_dotenv()

from tools import verify_patient, get_appointments, get_balance, search_patient_today


async def main():
    # Disable broadcasting for testing
    from tools import set_broadcast_fn
    captured = []

    async def fake_broadcast(msg):
        captured.append(msg)

    set_broadcast_fn(fake_broadcast)

    print("=" * 60)
    print("Testing verify_patient")
    print("=" * 60)
    # Try a common name — adjust to match your DB
    result = verify_patient.__wrapped__ if hasattr(verify_patient, "__wrapped__") else verify_patient
    r = await verify_patient("Smith", "1985-03-15")
    print(f"  Result: {r}")
    print()

    print("=" * 60)
    print("Testing search_patient_today (sync)")
    print("=" * 60)
    r = search_patient_today("Gar")  # partial last name search
    print(f"  Found {len(r['results'])} results")
    for apt in r["results"][:3]:
        print(f"    {apt['PatFName']} {apt['PatLName']} — {apt['time']} — {apt['procedure']}")
    print()

    # If we found a patient from search, test appointments + balance
    if r["results"]:
        pat_num = r["results"][0]["pat_num"]
        print("=" * 60)
        print(f"Testing get_appointments (PatNum={pat_num})")
        print("=" * 60)
        r2 = await get_appointments(str(pat_num))
        print(f"  Result: {r2}")
        print()

        print("=" * 60)
        print(f"Testing get_balance (PatNum={pat_num})")
        print("=" * 60)
        r3 = await get_balance(str(pat_num))
        print(f"  Result: {r3}")
        print()

    print("=" * 60)
    print(f"Broadcast events captured: {len(captured)}")
    for msg in captured:
        print(f"  {msg[:120]}...")
    print("=" * 60)
    print("All tests completed.")


if __name__ == "__main__":
    asyncio.run(main())
