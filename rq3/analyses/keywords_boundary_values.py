#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Unified VDB keyword loading module.

Provides utilities to load keyword config from JSON files for each VDB type, supporting:
- Field path mapping (field_path_mapping): field name → keyword type
- Keyword mapping (keyword_mapping): keyword type → list of valid values
- Excluded fields (excluded_data_fields): data fields that should not be mutated
"""

import os
import json
import logging
from typing import Dict, List, Optional, Any, Set
from pathlib import Path

logger = logging.getLogger('vdbfuzz.keywords')

# Keyword file directory
KEYWORDS_DIR = Path(__file__).parent

# Supported VDB types
SUPPORTED_VDB_TYPES = ['qdrant', 'weaviate', 'milvus']

# Cache for loaded keywords
_keywords_cache: Dict[str, Dict] = {}


def load_vdb_keywords(vdb_type: str) -> Dict[str, Any]:
    """
    Load keyword configuration for the specified VDB type
    
    Args:
        vdb_type: VDB type (qdrant/weaviate/milvus)
        
    Returns:
        dict: keyword config containing keyword_mapping, field_path_mapping, excluded_data_fields
    """
    vdb_type = vdb_type.lower()
    
    # Check cache
    if vdb_type in _keywords_cache:
        return _keywords_cache[vdb_type]
    
    # Load JSON file
    keywords_file = KEYWORDS_DIR / f'{vdb_type}_keywords.json'
    
    if not keywords_file.exists():
        logger.warning(f"Keyword file not found: {keywords_file}")
        return _get_empty_keywords()
    
    try:
        with open(keywords_file, 'r', encoding='utf-8') as f:
            keywords = json.load(f)
        
        # Ensure required fields
        if 'keyword_mapping' not in keywords:
            keywords['keyword_mapping'] = {}
        if 'field_path_mapping' not in keywords:
            keywords['field_path_mapping'] = {}
        if 'excluded_data_fields' not in keywords:
            keywords['excluded_data_fields'] = []
        
        # Cache
        _keywords_cache[vdb_type] = keywords
        logger.info(f"Loaded {vdb_type} keyword config: {len(keywords['keyword_mapping'])} types, "
                   f"{len(keywords['field_path_mapping'])} field mappings")
        
        return keywords
        
    except (json.JSONDecodeError, Exception) as e:
        logger.error(f"Failed to load keyword file {keywords_file}: {e}")
        return _get_empty_keywords()


def _get_empty_keywords() -> Dict[str, Any]:
    """Return an empty keyword configuration"""
    return {
        'keyword_mapping': {},
        'field_path_mapping': {},
        'excluded_data_fields': [],
        'field_relationships': {}
    }


def get_field_type(vdb_type: str, field_name: str) -> Optional[str]:
    """
    Get keyword type by field name
    
    Args:
        vdb_type: VDB type
        field_name: field name
        
    Returns:
        str: keyword type such as 'distance_metrics'; None if not found
    """
    keywords = load_vdb_keywords(vdb_type)
    field_path_mapping = keywords.get('field_path_mapping', {})
    
    # Exact match
    if field_name in field_path_mapping:
        return field_path_mapping[field_name]
    
    # Case-insensitive match
    field_name_lower = field_name.lower()
    for key, value in field_path_mapping.items():
        if key.lower() == field_name_lower:
            return value
    
    return None


def get_keyword_values(vdb_type: str, keyword_type: str) -> List[Any]:
    """
    Get all valid values for the given keyword type
    
    Args:
        vdb_type: VDB type
        keyword_type: keyword type such as 'distance_metrics'
        
    Returns:
        list: valid values
    """
    keywords = load_vdb_keywords(vdb_type)
    keyword_mapping = keywords.get('keyword_mapping', {})
    
    return keyword_mapping.get(keyword_type, [])


def is_excluded_field(vdb_type: str, field_name: str) -> bool:
    """
    Check whether a field is excluded from mutation
    
    Args:
        vdb_type: VDB type
        field_name: field name
        
    Returns:
        bool: whether the field is excluded
    """
    keywords = load_vdb_keywords(vdb_type)
    excluded = keywords.get('excluded_data_fields', [])
    
    field_name_lower = field_name.lower()
    return any(ex.lower() == field_name_lower for ex in excluded)


def get_mutations_for_field(vdb_type: str, field_name: str, current_value: Any) -> List[Any]:
    """
    Generate mutation list based on field name and current value
    
    Core mutation function that matches keyword type via field path, then returns all valid values of that type excluding the current one.
    
    Args:
        vdb_type: VDB type
        field_name: field name (last segment of JSON path)
        current_value: current value
        
    Returns:
        list: mutation values; empty list if not a metadata field
    """
    # Check excluded field
    if is_excluded_field(vdb_type, field_name):
        return []
    
    # Get keyword type for the field
    keyword_type = get_field_type(vdb_type, field_name)
    
    if not keyword_type:
        # Not a known metadata field; no mutation
        return []
    
    # Get valid values for the type
    valid_values = get_keyword_values(vdb_type, keyword_type)
    
    if not valid_values:
        return []
    
    # Build mutation list excluding current value
    current_str = str(current_value).lower() if current_value is not None else ""
    mutations = []
    
    for val in valid_values:
        val_str = str(val).lower()
        if val_str != current_str:
            mutations.append(val)
    
    # Add an invalid value for boundary testing
    mutations.append(f"invalid_{keyword_type}")
    
    return mutations


def get_mutations_by_value(vdb_type: str, value: str) -> List[str]:
    """
    Match keyword type by value and return mutation list.
    
    When field name is unavailable, try to infer type by value.
    
    Args:
        vdb_type: VDB type
        value: current value
        
    Returns:
        list: mutation values
    """
    if not value:
        return []
    
    keywords = load_vdb_keywords(vdb_type)
    keyword_mapping = keywords.get('keyword_mapping', {})
    value_lower = value.lower()
    
    # Traverse all keyword types to find a match by value
    for keyword_type, valid_values in keyword_mapping.items():
        # Check if value is in the valid list
        valid_values_lower = [str(v).lower() for v in valid_values]
        if value_lower in valid_values_lower:
            # Found match, return other valid values
            mutations = [v for v in valid_values if str(v).lower() != value_lower]
            mutations.append(f"invalid_{keyword_type}")
            return mutations
    
    return []


def get_all_meta_field_names(vdb_type: str) -> Set[str]:
    """
    Get all metadata field names (fields subject to mutation)
    
    Args:
        vdb_type: VDB type
        
    Returns:
        set: metadata field names
    """
    keywords = load_vdb_keywords(vdb_type)
    field_path_mapping = keywords.get('field_path_mapping', {})
    return set(field_path_mapping.keys())


def get_all_excluded_field_names(vdb_type: str) -> Set[str]:
    """
    Get all excluded field names (fields not mutated)
    
    Args:
        vdb_type: VDB type
        
    Returns:
        set: excluded field names
    """
    keywords = load_vdb_keywords(vdb_type)
    return set(keywords.get('excluded_data_fields', []))


# Exported common keywords (backward compatibility)
VDB_KEYWORDS = {
    "similarity_metrics": {
        "cosine": ["dot", "euclidean", "manhattan"],
        "dot": ["cosine", "euclidean", "manhattan"],
        "euclidean": ["cosine", "dot", "manhattan"],
        "manhattan": ["cosine", "dot", "euclidean"]
    },
    "index_types": {
        "hnsw": ["flat", "ivf", "pq"],
        "flat": ["hnsw", "ivf", "pq"],
        "ivf": ["hnsw", "flat", "pq"]
    },
    "operations": {
        "search": ["find", "query", "get"],
        "create": ["insert", "add", "make"],
        "delete": ["remove", "erase", "drop"],
        "update": ["modify", "change", "alter"]
    }
}

# Special string mutation set (for security testing)
SPECIAL_STRING_MUTATIONS = [
    "",                                 # Empty string
    "null",                             # Special literal
    "A" * 1000,                         # Overlong string
    "SELECT * FROM collections",        # SQL-injection style
    "<script>alert(1)</script>",        # XSS style
    "../../../etc/passwd",              # Path traversal style
    "{{7*7}}",                          # Template injection style
    "\u0000harmful",                    # Null-byte injection
    " OR 1=1 --"                        # SQL injection condition
]

# Integer boundary values
INTEGER_BOUNDARY_VALUES = [
    0, 1, -1,
    127, 128, 255, 256, -128, -129,
    32767, 32768, 65535, 65536, -32768, -32769,
]
