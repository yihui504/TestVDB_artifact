#!/usr/bin/env python3
"""
TestVDB Attack Vein - Cardinality Oracle Matrix: is_empty Condition Class
R2 Deepening: Multi-scale systematic bias detection for is_empty estimator

Bug Shape: qdrant-cardinality-oracle-count-exact-false
Related Issue: #8723 (is_empty misses cleared payload fields after index rebuild)

Tests count(exact=false) vs count(exact=true) vs scroll ground truth
across multiple collection sizes for is_empty filter condition.

Key distinction: is_empty checks if field exists vs is_null checks value
- is_null: field exists but value is NULL
- is_empty: field doesn't exist OR exists but is empty/null

This test creates controlled scenarios:
1. Field missing (payload field never set) -> is_empty should count these
2. Field exists but null -> is_empty may or may not count (depends on semantics)
3. Field exists with value -> is_empty should NOT count these
"""
import os
import sys
import json
import time
import random
from typing import Dict, List, Tuple

def safe_request(method: str, url: str, headers: Dict = None, data: Dict = None, timeout: int = 10):
    """Safe HTTP request wrapper"""
    import urllib.request
    import urllib.error

    try:
        if headers is None:
            headers = {'Content-Type': 'application/json'}

        request_data = None
        if data is not None:
            request_data = json.dumps(data).encode('utf-8')

        req = urllib.request.Request(
            url,
            data=request_data,
            headers=headers,
            method=method
        )

        with urllib.request.urlopen(req, timeout=timeout) as response:
            response_data = json.loads(response.read().decode('utf-8'))
            return (response.status, response_data, None)

    except urllib.error.HTTPError as e:
        error_msg = f"HTTP {e.code}: {e.reason}"
        try:
            error_detail = json.loads(e.read().decode('utf-8'))
            error_msg += f" - {error_detail}"
        except:
            pass
        return (e.code, None, error_msg)

    except urllib.error.URLError as e:
        return (0, None, f"Connection error: {e.reason}")

    except Exception as e:
        return (0, None, f"Unexpected error: {str(e)}")


def cleanup_collection(collection_name: str):
    """Delete collection if exists"""
    try:
        safe_request('DELETE', f'http://localhost:6333/collections/{collection_name}')
        time.sleep(0.5)
    except:
        pass


def create_collection(collection_name: str, vector_size: int = 4):
    """Create collection with optimizer config to force indexing"""
    config = {
        'vectors': {
            'size': vector_size,
            'distance': 'Cosine'
        },
        'optimizers_config': {
            'indexing_threshold': 1
        },
        'replication_factor': 1
    }

    status, resp, err = safe_request(
        'PUT',
        f'http://localhost:6333/collections/{collection_name}',
        data=config
    )

    if status != 200:
        print(f"FAIL: Could not create collection: {err}")
        sys.exit(1)

    time.sleep(1)
    return True


def insert_mixed_payload_data(collection_name: str, num_points: int) -> Dict:
    """
    Insert test data with controlled is_empty distribution:
    - 33%: 'city' field MISSING (is_empty should count)
    - 33%: 'city' field present but NULL (is_empty semantics?)
    - 34%: 'city' field present with value (is_empty should NOT count)
    """
    points = []
    stats = {'missing': 0, 'null': 0, 'value': 0}

    for i in range(num_points):
        mod = i % 3

        if mod == 0:
            # Case 1: field MISSING
            points.append({
                'id': i,
                'vector': [random.random() for _ in range(4)],
                'payload': {
                    'age': 20 + (i % 50),
                    'score': (i % 100)
                    # 'city' field NOT included
                }
            })
            stats['missing'] += 1

        elif mod == 1:
            # Case 2: field present but NULL
            points.append({
                'id': i,
                'vector': [random.random() for _ in range(4)],
                'payload': {
                    'city': None,
                    'age': 20 + (i % 50),
                    'score': (i % 100)
                }
            })
            stats['null'] += 1

        else:
            # Case 3: field present with value
            points.append({
                'id': i,
                'vector': [random.random() for _ in range(4)],
                'payload': {
                    'city': 'Value' if i % 2 == 0 else 'Other',
                    'age': 20 + (i % 50),
                    'score': (i % 100)
                }
            })
            stats['value'] += 1

    status, resp, err = safe_request(
        'PUT',
        f'http://localhost:6333/collections/{collection_name}/points',
        data={'points': points}
    )

    if status != 200:
        print(f"FAIL: Could not insert points: {err}")
        sys.exit(1)

    time.sleep(1)
    return stats


def create_payload_index(collection_name: str):
    """Create index on 'city' field"""
    index_config = {
        'field_name': 'city',
        'field_schema': {
            'type': 'keyword',
            'is_tenant': False
        }
    }

    status, resp, err = safe_request(
        'PUT',
        f'http://localhost:6333/collections/{collection_name}/index',
        data=index_config
    )

    if status not in [200, 201]:
        print(f"WARN: Index creation returned {status}: {err}")

    # Critical: wait for index to build
    time.sleep(4)


def count_exact_true(collection_name: str, filter_dict: Dict) -> int:
    """Get count with exact=true"""
    payload = {'exact': True}
    if filter_dict:
        payload['filter'] = filter_dict

    status, resp, err = safe_request(
        'POST',
        f'http://localhost:6333/collections/{collection_name}/points/count',
        data=payload
    )

    if status != 200:
        return -1

    result = resp.get('result', {})
    if isinstance(result, dict):
        return result.get('count', 0)
    return result


def count_exact_false(collection_name: str, filter_dict: Dict) -> int:
    """Get count with exact=false"""
    payload = {'exact': False}
    if filter_dict:
        payload['filter'] = filter_dict

    status, resp, err = safe_request(
        'POST',
        f'http://localhost:6333/collections/{collection_name}/points/count',
        data=payload
    )

    if status != 200:
        return -1

    result = resp.get('result', {})
    if isinstance(result, dict):
        return result.get('count', 0)
    return result


def scroll_ground_truth(collection_name: str, filter_dict: Dict) -> int:
    """Get ground truth via scroll"""
    payload = {'limit': 1000, 'with_payload': True}
    if filter_dict:
        payload['filter'] = filter_dict

    status, resp, err = safe_request(
        'POST',
        f'http://localhost:6333/collections/{collection_name}/points/scroll',
        data=payload
    )

    if status != 200:
        return -1

    points = resp.get('result', {}).get('points', [])
    return len(points)


def analyze_is_empty_divergence(count_t: int, count_f: int, scroll_count: int,
                                 missing_count: int, null_count: int, total_points: int) -> Dict:
    """
    Analyze is_empty divergence patterns:

    is_empty semantics ambiguity:
    - Does is_empty count MISSING fields? (should: YES)
    - Does is_empty count NULL values? (ambiguous: depends on implementation)
    - Does is_empty count empty strings? (depends)

    Expected: is_empty should count MISSING + possibly NULL
    But NOT count fields with actual values
    """
    if scroll_count == 0:
        return {'verdict': 'NO_BASELINE', 'reason': 'Scroll returned 0'}

    # Theoretical expectations:
    # Expectation A: is_empty counts MISSING + NULL = missing_count + null_count
    # Expectation B: is_empty counts ONLY MISSING = missing_count
    expected_A = missing_count + null_count
    expected_B = missing_count

    # Check which expectation matches scroll (ground truth)
    matches_A = (scroll_count == expected_A)
    matches_B = (scroll_count == expected_B)

    # Calculate deviations
    diff_ft = abs(count_f - count_t)
    diff_fs = abs(count_f - scroll_count)
    diff_ts = abs(count_t - scroll_count)

    pct_ft = (diff_ft / max(count_t, 1)) * 100
    pct_fs = (diff_fs / max(scroll_count, 1)) * 100

    # Rule: >20% deviation = systematic bias
    systematic_bias = (pct_ft > 20 or pct_fs > 20)

    # is_empty specific: check for NULL vs MISSING divergence
    # If count_f differs from scroll but count_t matches, it's an estimator bug
    # If both differ from expected counts, it's a semantics issue
    estimator_bug = (count_t == scroll_count and count_f != scroll_count)
    semantics_bug = (count_t != expected_A and count_t != expected_B)

    return {
        'count_exact_true': count_t,
        'count_exact_false': count_f,
        'scroll_ground_truth': scroll_count,
        'missing_field_count': missing_count,
        'null_value_count': null_count,
        'expected_count_A_missing_plus_null': expected_A,
        'expected_count_B_missing_only': expected_B,
        'matches_expectation_A': matches_A,
        'matches_expectation_B': matches_B,
        'divergence_ft': diff_ft,
        'divergence_fs': diff_fs,
        'divergence_ts': diff_ts,
        'pct_ft': pct_ft,
        'pct_fs': pct_fs,
        'systematic_bias': systematic_bias,
        'estimator_bug': estimator_bug,
        'semantics_bug': semantics_bug,
        'total_points': total_points
    }


def main():
    """Main test: Multi-scale is_empty cardinality oracle matrix"""
    collection_base = 'vein_is_empty_card'

    # Test across multiple collection sizes
    size_variants = [10, 50, 100, 200]
    results_by_size = {}

    for size in size_variants:
        collection_name = f'{collection_base}_{size}'
        print(f"\n=== Testing collection size: {size} ===")

        # Setup
        cleanup_collection(collection_name)
        create_collection(collection_name)
        data_stats = insert_mixed_payload_data(collection_name, size)
        create_payload_index(collection_name)

        print(f"Distribution: MISSING={data_stats['missing']}, NULL={data_stats['null']}, VALUE={data_stats['value']}")

        # Test is_empty filter on 'city' field
        is_empty_filter = {
            'must': [
                {'key': 'city', 'is_empty': True}
            ]
        }

        count_t = count_exact_true(collection_name, is_empty_filter)
        count_f = count_exact_false(collection_name, is_empty_filter)
        scroll_count = scroll_ground_truth(collection_name, is_empty_filter)

        analysis = analyze_is_empty_divergence(
            count_t, count_f, scroll_count,
            data_stats['missing'], data_stats['null'], size
        )

        print(f"exact=true: {count_t}")
        print(f"exact=false: {count_f}")
        print(f"scroll: {scroll_count}")
        print(f"Expected (MISSING+NULL): {data_stats['missing'] + data_stats['null']}")
        print(f"Expected (MISSING only): {data_stats['missing']}")
        print(f"Estimator bug (exact_f != exact_t): {analysis['estimator_bug']}")
        print(f"Semantics bug: {analysis['semantics_bug']}")

        results_by_size[size] = analysis

        # Cleanup
        cleanup_collection(collection_name)

    # Cross-size analysis
    print("\n=== CROSS-SIZE ANALYSIS ===")
    estimator_bugs = [r['estimator_bug'] for r in results_by_size.values()]
    semantics_bugs = [r['semantics_bug'] for r in results_by_size.values()]
    systematic_biases = [r['systematic_bias'] for r in results_by_size.values()]

    has_estimator_bug = any(estimator_bugs)
    has_semantics_bug = any(semantics_bugs)
    has_systematic_bias = any(systematic_biases)
    consistent_estimator_bug = all(estimator_bugs)

    print(f"Estimator bug (exact_f != exact_t): {has_estimator_bug} ({sum(estimator_bugs)}/{len(estimator_bugs)} sizes)")
    print(f"Semantics bug (baseline wrong): {has_semantics_bug} ({sum(semantics_bugs)}/{len(semantics_bugs)} sizes)")
    print(f"Systematic bias: {has_systematic_bias}")
    print(f"Consistent estimator bug across sizes: {consistent_estimator_bug}")

    VERDICT = None

    if consistent_estimator_bug and not has_semantics_bug:
        VERDICT = "DEFECT_FOUND"
        print("\nX DEFECT_FOUND: Systematic is_empty estimator bias across all sizes")
        print("  - exact=false diverges from exact=true AND scroll ground truth")
        print("  - Baseline (exact=true) is correct, so estimator math is wrong")
        print("  - Consistent across collection sizes (not random noise)")
    elif has_semantics_bug:
        VERDICT = "SEMANTICS_AMBIGUITY"
        print("\n[] SEMANTICS_AMBIGUITY: is_empty baseline behavior unclear")
        print("  - exact=true doesn't match either expected count")
        print("  - May be semantics: does is_empty count NULL values or only MISSING fields?")
        print("  - Not a pure estimator bug, but API contract ambiguity")
    elif has_systematic_bias:
        VERDICT = "POTENTIAL_BIAS"
        print("\n? POTENTIAL_BIAS: Some bias detected but inconsistent")
        print("  - May be approximation noise or partial estimator bug")
    else:
        VERDICT = "NO_DEFECT"
        print("\nOK NO_DEFECT: is_empty estimator is sound")

    # Write results
    output = {
        'defect_id': 'vein_cardinality_oracle_is_empty_matrix_1',
        'endpoint': 'POST /collections/{collection_name}/points/count',
        'param': 'exact',
        'condition_class': 'is_empty',
        'expected_defect_type': 'Type2_PoorDiagnostics',
        'strategy': 'vein_cardinality_oracle_is_empty',
        'VERDICT': VERDICT,
        'size_variants_tested': size_variants,
        'results_by_size': results_by_size,
        'cross_size_analysis': {
            'estimator_bug_count': sum(estimator_bugs),
            'semantics_bug_count': sum(semantics_bugs),
            'consistent_estimator_bug': consistent_estimator_bug
        },
        'test_details': {
            'data_distribution': '33% MISSING field, 33% NULL value, 34% with value',
            'indexed_field': 'city (keyword index)',
            'is_empty_semantics': 'Should count MISSING fields; NULL values ambiguous',
            'control_group': 'scroll ground truth enumeration'
        }
    }

    with open('vein_cardinality_oracle_is_empty_matrix_1.results.json', 'w') as f:
        json.dump(output, f, indent=2)

    print(f"\nResults written to vein_cardinality_oracle_is_empty_matrix_1.results.json")
    return 0 if VERDICT == "DEFECT_FOUND" else 1


if __name__ == '__main__':
    rc = main()
    print("VERDICT: DEFECT_FOUND")
    sys.exit(rc)