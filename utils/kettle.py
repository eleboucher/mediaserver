import asyncio

from bleak import BleakScanner


async def find_kettle():
    print("Scanning for Fellow Stagg EKG Pro... (5 seconds)")
    devices = await BleakScanner.discover(timeout=5.0)

    found = False
    for d in devices:
        # Check if it looks like a kettle
        name = d.name or "Unknown"
        if "stagg" in name.lower() or "fellow" in name.lower() or "ekg" in name.lower():
            print(f"✅ FOUND IT: {name}")
            print(f"   MAC Address: {d.address}")
            found = True

    if not found:
        print("❌ Not found. Make sure the kettle is plugged in and nearby.")
        print("   List of all devices found:")
        for d in devices:
            if d.name:
                print(f"   - {d.name}: {d.address}")


asyncio.run(find_kettle())
