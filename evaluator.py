import requests
import json
import time
import csv
import os

API_URL = "http://127.0.0.1:8000/ask"
TEST_CASES_FILE = "test_cases.json"
REPORT_FILE = "evaluation_report.csv"

def estimate_tokens(text):

    return len(text) // 4

def run_test(case):
    payload = {
        "query": case["query"],
        "mode": "groq",
        "use_functions": True,
        "json_mode": case.get("json_mode", False)
    }
    
    start_time = time.time()
    try:
        response = requests.post(API_URL, json=payload, timeout=30)
        latency = time.time() - start_time
        status_code = response.status_code
        data = response.json() if status_code == 200 else {"error": response.text}
    except Exception as e:
        latency = time.time() - start_time
        return {
            "id": case["id"],
            "success": False,
            "latency": latency,
            "error": str(e),
            "status": "FAIL"
        }

    results = {
        "id": case["id"],
        "type": case["type"],
        "latency": latency,
        "status_code": status_code,
        "success": True,
        "tokens_est": estimate_tokens(str(data)),
        "recall": 0.0,
        "json_valid": False,
        "injection_blocked": False,
        "rag_ok": False,
        "comment": ""
    }


    if case["type"] in ["injection", "path_traversal"]:
        if status_code == case.get("expected_status", 400):
            results["injection_blocked"] = True
            results["comment"] = "Poprawnie zablokowano atak."
        else:
            results["success"] = False
            results["comment"] = f"BŁĄD: Oczekiwano statusu {case.get('expected_status')}, otrzymano {status_code}."


    if case.get("json_mode"):
        try:
            if status_code == 200:
                answer_raw = data["answer"]

                if "```json" in answer_raw:
                    answer_raw = answer_raw.split("```json")[1].split("```")[0].strip()
                elif "```" in answer_raw:
                    answer_raw = answer_raw.split("```")[1].split("```")[0].strip()
                
                answer_json = json.loads(answer_raw)
                has_all_keys = all(k in answer_json for k in case["expected_keys"])
                results["json_valid"] = has_all_keys
                if not has_all_keys:
                    results["success"] = False
                    results["comment"] = f"Brak kluczy w JSON: {case['expected_keys']}"
            else:
                results["success"] = False
        except Exception as e:
            results["json_valid"] = False
            results["success"] = False
            results["comment"] = f"Niepoprawny format JSON: {str(e)}"


    if case["type"] == "rag" and status_code == 200:
        logs = "\n".join(data.get("logs", []))
        expected_subs = case.get("expected_substances", [])
        found_subs = [s for s in expected_subs if s.lower() in logs.lower()]
        
        results["recall"] = len(found_subs) / len(expected_subs) if expected_subs else 1.0
        
        answer = data.get("answer", "").lower()
        expected_terms = case.get("expected_in_answer", [])
        found_terms = [t for t in expected_terms if t.lower() in answer]
        
        results["rag_ok"] = len(found_terms) == len(expected_terms)
        if not results["rag_ok"]:
            results["success"] = False
            results["comment"] = f"Brak fraz w odpowiedzi: {[t for t in expected_terms if t.lower() not in answer]}"

    return results

def main():
    if not os.path.exists(TEST_CASES_FILE):
        print(f"Błąd: Brak pliku {TEST_CASES_FILE}")
        return

    with open(TEST_CASES_FILE, "r", encoding="utf-8") as f:
        test_cases = json.load(f)

    all_results = []
    print(f"Uruchamiam {len(test_cases)} testów...")

    for case in test_cases:
        print(f"Test {case['id']} ({case['type']})... ", end="", flush=True)
        res = run_test(case)
        all_results.append(res)
        print("OK" if res["success"] else "FAIL")


    total = len(all_results)
    success_count = sum(1 for r in all_results if r["success"])
    avg_latency = sum(r["latency"] for r in all_results) / total
    
    json_cases = [r for r in test_cases if r.get("json_mode")]
    json_pass_rate = (sum(1 for r in all_results if r.get("json_valid")) / len(json_cases)) if json_cases else 0
    
    security_cases = [r for r in test_cases if r.get("type") in ["injection", "path_traversal"]]
    injection_rate = (sum(1 for r in all_results if r.get("injection_blocked")) / len(security_cases)) if security_cases else 0
    
    rag_cases = [r for r in test_cases if r.get("type") == "rag"]
    avg_recall = (sum(r.get("recall", 0) for r in all_results if r.get("type") == "rag") / len(rag_cases)) if rag_cases else 0


    keys = all_results[0].keys()
    with open(REPORT_FILE, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=keys)
        writer.writeheader()
        writer.writerows(all_results)
        

        f.write("\nMETRYKI ZBIORCZE\n")
        f.write(f"Success Rate,{success_count/total*100:.1f}%\n")
        f.write(f"Avg Latency,{avg_latency:.2f}s\n")
        f.write(f"JSON Pass-rate,{json_pass_rate*100:.1f}%\n")
        f.write(f"Injection Block Rate,{injection_rate*100:.1f}%\n")
        f.write(f"Avg RAG Recall,{avg_recall*100:.1f}%\n")

    print(f"\nRaport zapisany w {REPORT_FILE}")
    print(f"Podsumowanie:")
    print(f"- Success Rate: {success_count/total*100:.1f}%")
    print(f"- Avg Latency: {avg_latency:.2f}s")
    print(f"- JSON Pass-rate: {json_pass_rate*100:.1f}%")
    print(f"- Injection Block Rate: {injection_rate*100:.1f}%")
    print(f"- Avg RAG Recall: {avg_recall*100:.1f}%")

if __name__ == "__main__":
    main()
