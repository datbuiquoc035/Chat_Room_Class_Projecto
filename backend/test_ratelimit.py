import urllib.request
import urllib.error
import time
import sys

url = "http://127.0.0.1:8000/rooms"
print(f"Spamming {url} 15 times to test Rate Limiting (Limit: 10/min)...")

success_count = 0
rate_limited_count = 0

for i in range(1, 16):
    try:
        req = urllib.request.Request(url)
        with urllib.request.urlopen(req) as response:
            code = response.getcode()
            print(f"Request {i}: HTTP {code}")
            if code == 200:
                success_count += 1
    except urllib.error.HTTPError as e:
        print(f"Request {i}: HTTP {e.code} - {e.reason}")
        if e.code == 429:
            rate_limited_count += 1
    except Exception as e:
        print(f"Request {i}: Error {e}")
    
    time.sleep(0.1)

print("--- Test Summary ---")
print(f"Successful (200 OK): {success_count} (Expected: 10)")
print(f"Rate Limited (429 Too Many Requests): {rate_limited_count} (Expected: 5)")

if success_count == 10 and rate_limited_count == 5:
    print("TEST PASSED: Rate Limiter is working correctly!")
else:
    print("TEST NOTE: Results depend on existing request count in the current minute window.")
