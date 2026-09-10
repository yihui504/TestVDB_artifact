#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Vector Database (VDB) fuzzing tool - data mutation module.

This module provides mutation strategies for various data types, with a focus on
integers, booleans, and key string data. It implements exhaustive mutation
testing to systematically exercise every mutable value in request content.
"""

import sys
import json
import copy
import uuid
import time
import random
import logging
import sys
import json
import copy
import signal
from datetime import datetime
import requests

from typing import Dict, List, Tuple, Union, Any, Callable, Optional, Set
from collections import defaultdict

# Import from the unified keyword module
from .keywords import (
    VDB_KEYWORDS, INTEGER_BOUNDARY_VALUES, SPECIAL_STRING_MUTATIONS,
    load_vdb_keywords, get_field_type, get_keyword_values,
    is_excluded_field, get_mutations_for_field, get_mutations_by_value
)
# Keep legacy mutation functions as fallback
from .mutateqdrantstring import mutate_qdrant_string
from .mutateweaviatestring import mutate_weaviate_string

# Get logger instance; relies on root logger configuration
logger = logging.getLogger('vdbfuzz.mutator')


VDBINTEGERNAME = ["ef", "size", "dim", "max_capacity", "limit", "offset",
"efconstruction", "dynamicefmin", "dynamicefmax", "dynamiceffactor","flatsearchcutoff","segments",
'top_k', "nprobe", "nlist", 
"shardsnum", "partitionsnum", "dimension"]

class Mutator:
    """Data mutator providing mutation strategies for multiple data types"""
    
    # Supported VDB types
    SUPPORTED_VDB_TYPES = ['qdrant', 'weaviate', 'milvus']
    
    def __init__(self, vdb_type: str = None):
        """
        Initialize the data mutator
        
        Args:
            vdb_type: target vector database type (qdrant/weaviate/milvus) for targeted mutations
        """
        self.mutation_results = []
        self.vdb_type = vdb_type.lower() if vdb_type else None
        if self.vdb_type and self.vdb_type not in self.SUPPORTED_VDB_TYPES:
            logger.warning(f"Unsupported VDB type: {vdb_type}, falling back to generic mutations")
            self.vdb_type = None
    
    def get_mutation_candidates(self, content: Dict) -> Dict[str, List[Tuple[List[Union[str, int]], Any]]]:
        """
        Recursively traverse content and identify all mutable integers, booleans,
        and VDB meta-information strings.
        
        Uses field-path matching to mutate only VDB metadata fields (e.g., distance,
        vectorIndexType) while excluding data fields (e.g., collection, vector).
        
        Args:
            content: request content object
            
        Returns:
            dict: {
                'integers': [(path, value)], 
                'booleans': [(path, value)],
                'vdb_strings': [(path, value, keyword_type)],
                'float_arrays': [(path, dimension, is_multi_dim, dimensions)]
            }
        """
        result = {
            "integers": [], 
            "booleans": [], 
            "vdb_strings": [],
            "float_arrays": []
        }
        
        # Load keyword config for the current VDB type
        vdb_keywords_config = load_vdb_keywords(self.vdb_type) if self.vdb_type else {}
        field_path_mapping = vdb_keywords_config.get('field_path_mapping', {})
        keyword_mapping = vdb_keywords_config.get('keyword_mapping', {})
        excluded_fields = set(vdb_keywords_config.get('excluded_data_fields', []))
        
        def traverse(obj, path=[]):
            if isinstance(obj, dict):
                for key, value in obj.items():
                    new_path = path + [key]
                    
                    # Handle integers
                    if isinstance(value, int) and not isinstance(value, bool):
                        # Exclude likely IDs or timestamps (adjust as needed)
                        if key.lower() not in ["id", "timestamp", "time"] + VDBINTEGERNAME:
                            result["integers"].append((new_path, value))
                            
                    # Handle booleans
                    elif isinstance(value, bool):
                        result["booleans"].append((new_path, value))
                        
                    # Handle strings - mutate only VDB metadata fields
                    elif isinstance(value, str):
                        # Check float array placeholders
                        if value.startswith("__FLOAT_ARRAY_DIM_"):
                            try:
                                dimension = int(value.replace("__FLOAT_ARRAY_DIM_", "").replace("__", ""))
                                result["float_arrays"].append((new_path, dimension, False, [dimension]))
                            except ValueError:
                                pass
                        elif value.startswith("__FLOAT_MULTI_DIM_"):
                            try:
                                dims_str = value.replace("__FLOAT_MULTI_DIM_", "").replace("__", "")
                                dimensions = [int(dim) for dim in dims_str.split(',')]
                                result["float_arrays"].append((new_path, sum(dimensions), True, dimensions))
                            except (ValueError, IndexError):
                                pass
                        else:
                            # Get field name (last part of path)
                            field_name = str(key)
                            
                            # 1. Skip excluded data fields
                            if field_name.lower() in [f.lower() for f in excluded_fields]:
                                pass  # skip data fields
                            
                            # 2. Exact match against field_path_mapping for metadata fields
                            elif field_name in field_path_mapping:
                                keyword_type = field_path_mapping[field_name]
                                result["vdb_strings"].append((new_path, value, keyword_type))
                            
                            # 3. Case-insensitive match
                            else:
                                field_name_lower = field_name.lower()
                                matched = False
                                for mapped_field, keyword_type in field_path_mapping.items():
                                    if mapped_field.lower() == field_name_lower:
                                        result["vdb_strings"].append((new_path, value, keyword_type))
                                        matched = True
                                        break
                                
                                # 4. Fallback: match by value against keyword sets
                                if not matched and value and keyword_mapping:
                                    value_lower = value.lower()
                                    for keyword_type, valid_values in keyword_mapping.items():
                                        if value_lower in [str(v).lower() for v in valid_values]:
                                            result["vdb_strings"].append((new_path, value, keyword_type))
                                            break
                    
                    # Recurse into nested structures
                    if isinstance(value, (dict, list)):
                        traverse(value, new_path)
                        
            elif isinstance(obj, list):
                for i, item in enumerate(obj):
                    new_path = path + [i]
                    
                    # Handle basic types
                    if isinstance(item, int) and not isinstance(item, bool):
                        result["integers"].append((new_path, item))
                    elif isinstance(item, bool):
                        result["booleans"].append((new_path, item))
                    elif isinstance(item, str):
                        # Check float array placeholders
                        if item.startswith("__FLOAT_ARRAY_DIM_"):
                            try:
                                dimension = int(item.replace("__FLOAT_ARRAY_DIM_", "").replace("__", ""))
                                result["float_arrays"].append((new_path, dimension, False, [dimension]))
                            except ValueError:
                                pass
                        elif item.startswith("__FLOAT_MULTI_DIM_"):
                            try:
                                dims_str = item.replace("__FLOAT_MULTI_DIM_", "").replace("__", "")
                                dimensions = [int(dim) for dim in dims_str.split(',')]
                                result["float_arrays"].append((new_path, sum(dimensions), True, dimensions))
                            except (ValueError, IndexError):
                                pass
                        # Strings in lists: match keyword type by value only
                        elif item and keyword_mapping:
                            item_lower = item.lower()
                            for keyword_type, valid_values in keyword_mapping.items():
                                if item_lower in [str(v).lower() for v in valid_values]:
                                    result["vdb_strings"].append((new_path, item, keyword_type))
                                    break
                        
                    # Recurse into nested structures
                    if isinstance(item, (dict, list)):
                        traverse(item, new_path)
        
        traverse(content)
        return result
    
    @staticmethod
    def mutate_integer(value: int) -> List[int]:
        """
        Mutate an integer value; return all boundary candidates
        
        Args:
            value: original integer value
            
        Returns:
            list: mutated integer values
        """
        # Return predefined boundary values for exhaustive testing
        return INTEGER_BOUNDARY_VALUES
    
    @staticmethod
    def mutate_boolean(value: bool) -> List[bool]:
        """
        Mutate a boolean by flipping it
        
        Args:
            value: original boolean value
            
        Returns:
            list: mutated boolean values (just flipped)
        """
        return [not value]
        
    @staticmethod
    def mutate_array_dimension(dimension: int, is_multi_dim: bool = False, dimensions: List[int] = None) -> List[Union[int, List[int]]]:
        """
        Mutate array dimensions; return mutated dimension candidates
        
        Args:
            dimension: original dimension or summed dimensions
            is_multi_dim: whether it's a multi-dimensional array
            dimensions: original dimension list for multi-d arrays
            
        Returns:
            list: mutated dimension values
        """
        results = []
        
        # Common dimension boundary candidates
        common_dimensions = [
            0,
            768,                            # BERT embedding dim
            1024,                           # 2^10, common large dim
            1536,                           # Newer OpenAI embedding dim
            10000,                          # Very large dim
        ]
        
        # Single-dimension: add common and variant sizes
        if not is_multi_dim:
            # Add common boundaries when different from original
            for dim_candidate in common_dimensions:
                if dim_candidate != dimension:
                    results.append(dim_candidate)

        
        # Multi-dimensional handling
        if is_multi_dim and dimensions:
            if random.random() < 0.05:  # Apply 5% probability threshold
                # 1. Mutate each dimension separately
                for i, current_dim_value in enumerate(dimensions):
                    # Add boundary tests
                    key_dim_values = [0, 768, 1024, 1536, 10000]
                    for mutated_dim_value in key_dim_values:
                        if mutated_dim_value != current_dim_value:
                            new_dimensions_config = dimensions.copy()
                            new_dimensions_config[i] = mutated_dim_value
                            results.append(new_dimensions_config)
                            
                    # Edge cases
                    for boundary_dim_value in [0, -1]:
                        new_dimensions_config_boundary = dimensions.copy()
                        new_dimensions_config_boundary[i] = boundary_dim_value
                        results.append(new_dimensions_config_boundary)
        
        return results
    
    def mutate_string(self, value: str, keyword_type: str, field_path: List[Union[str, int]] = None, json_content: Dict = None) -> List[str]:
        """
        Mutate key strings based on VDB type and keyword type to return precise variants.
        
        Core logic: pull all valid values for keyword_type from {vdb}_keywords.json,
        exclude the current value, and add an invalid value for boundary testing.
        
        Args:
            value: original string value
            keyword_type: keyword type (e.g., distance_metrics, vector_index_types)
            field_path: path of the field in JSON
            json_content: original JSON content
            
        Returns:
            list: mutated string values
        """
        if not value:
            return []
        
        # Prefer unified keyword module for mutations first
        if self.vdb_type and keyword_type:
            valid_values = get_keyword_values(self.vdb_type, keyword_type)
            
            if valid_values:
                # Build mutation list: exclude current value
                value_lower = value.lower()
                mutations = [v for v in valid_values if str(v).lower() != value_lower]
                
                # Add an invalid value for boundary testing
                mutations.append(f"invalid_{keyword_type}")
                
                logger.debug(f"Field mutation [{keyword_type}]: {value} -> {mutations[:5]}...")
                return mutations
        
        # Fallback to legacy mutation functions if unified module misses
        if self.vdb_type == 'weaviate':
            return mutate_weaviate_string(value, keyword_type, field_path, json_content)
        elif self.vdb_type == 'qdrant':
            return mutate_qdrant_string(value, keyword_type, field_path)
        
        # Final fallback to generic mutation
        return self._mutate_string_generic(value, keyword_type, field_path)
    
    def _mutate_string_generic(self, value: str, keyword_type: str, field_path: List[Union[str, int]] = None) -> List[str]:
        """Generic string mutation for unknown VDB types or Milvus"""
            

        # Legacy generic mutation logic
        mutations = []
        value_lower = value.lower()
        
        # 1. Type-specific mutations
        if keyword_type == "similarity_metrics":
            # Similarity metric mutations
            if value_lower in VDB_KEYWORDS["similarity_metrics"]:
                # Use predefined mutations
                mutations.extend(VDB_KEYWORDS["similarity_metrics"][value_lower])
                # Add special variants
                mutations.append("invalid_metric")
                mutations.append(value + "_similarity")
        
        elif keyword_type == "index_types":
            # Index type mutations
            if value_lower in VDB_KEYWORDS["index_types"]:
                mutations.extend(VDB_KEYWORDS["index_types"][value_lower])
                mutations.append("invalid_index")
                mutations.append(value + "_index")
        
        elif keyword_type == "operations":
            # Operation type mutations
            if value_lower in VDB_KEYWORDS["operations"]:
                mutations.extend(VDB_KEYWORDS["operations"][value_lower])
                mutations.append("invalid_op")
        
        elif keyword_type == "collection":
            # Collection name mutations
            mutations.append("nonexistent_collection")
            mutations.append(value + "_nonexistent")
        
        # 2. Common injection-like mutations (choose likely-effective ones)
        mutations.append("")  # Empty string
        mutations.append("null")
        
        # Boundary test: overly long string (skip for collection names)
        if len(value) > 0 and keyword_type != "collection":
            mutations.append("A" * 2000)
        
        # 3. SQL injection style (for collection or query-like operations)
        if keyword_type in ["collection", "operations"] and "search" in value_lower:
            mutations.append("' OR 1=1 --")
            mutations.append("SELECT * FROM collections")
        
        # 4. Deduplicate and exclude original
        mutations = list(set([m for m in mutations if m != value]))
        
        # Limit mutation count
        if len(mutations) > 10:
            return mutations[:10]
            
        return mutations
        
    @staticmethod
    def generate_float_array(dimension: int, normalized: bool = False, min_val: float = -1.0, max_val: float = 1.0) -> List[float]:
        """
        Generate a float array of the given dimension (typical VDB vector data)
        
        Args:
            dimension: array dimension
            normalized: whether to L2-normalize to unit vector
            min_val: minimum random value
            max_val: maximum random value
            
        Returns:
            list: generated float array
        """
        import random
        import math
        
        # Generate random float array
        array = [random.uniform(min_val, max_val) for _ in range(dimension)]
        
        # Normalize if requested
        if normalized:
            # Compute L2 norm
            vector_length = math.sqrt(sum(x*x for x in array))
            
            # Avoid division by zero
            if vector_length > 0:
                array = [x / vector_length for x in array]
                
        return array
    
    @staticmethod
    def generate_multi_dim_array(dimensions: List[int], normalized: bool = False, min_val: float = -1.0, max_val: float = 1.0) -> List:
        """
        Generate multi-dimensional float arrays (matrix/tensor)
        
        Args:
            dimensions: list of dimensions, e.g., [3, 4] means 3x4 matrix
            normalized: whether to normalize each sub-vector
            min_val: minimum random value
            max_val: maximum random value
            
        Returns:
            list: generated multi-dimensional float array
        """
        import random
        import math
        
        if not dimensions:
            return []
            
        # Single dimension: fallback to vector generator
        if len(dimensions) == 1:
            return Mutator.generate_float_array(dimensions[0], normalized, min_val, max_val)
        
        # Handle 2D+ arrays
        current_dim = dimensions[0]
        remaining_dims = dimensions[1:]
        
        # Generate multi-dimensional array
        if len(remaining_dims) == 1:
            # 2D matrix: build each row
            return [
                Mutator.generate_float_array(remaining_dims[0], normalized, min_val, max_val)
                for _ in range(current_dim)
            ]
        else:
            # Higher dimensions: recurse
            return [
                Mutator.generate_multi_dim_array(remaining_dims, normalized, min_val, max_val)
                for _ in range(current_dim)
            ]
    
    @staticmethod
    def generate_embedding_matrix(rows: int, embedding_dim: int, normalized: bool = True) -> List[List[float]]:
        """
        Generate an embedding matrix for VDB testing
        
        Args:
            rows: number of rows (data points)
            embedding_dim: dimension of each embedding vector
            normalized: whether to normalize to unit vectors
            
        Returns:
            list: generated embedding matrix
        """
        return Mutator.generate_multi_dim_array([rows, embedding_dim], normalized)
    
    @staticmethod
    def set_value_at_path(content: Dict, path: List[Union[str, int]], value: Any) -> Dict:
        """
        Set value at the specified path
        
        Args:
            content: original content object
            path: target path
            value: value to set
            
        Returns:
            dict: updated content object
        """
        result = copy.deepcopy(content)
        current = result
        
        for i, key in enumerate(path):
            if i == len(path) - 1:
                current[key] = value
            else:
                current = current[key]
        
        return result
    
    def check_db_connectivity(self, request_function: Callable, *args, **kwargs) -> bool:
        """
        Check database connectivity
        
        Args:
            request_function: function to send a request
            args, kwargs: arguments passed to the request function
            
        Returns:
            bool: whether the database is reachable
        """
        try:
            response = request_function(*args, **kwargs)
            # Additional checks (e.g., status code) can be added here
            return response.status_code < 500
        except Exception as e:
            logger.error(f"Connectivity check failed: {str(e)}")
            return False
    
    def normal_mutate(
        self, 
        original_content: Dict, 
        send_request: Callable, 
        connectivity_check_func: Callable,
        save_failure_func: Callable = None,
        max_time_minutes: int = 10,
        max_iterations: int = 100,
        mutation_ratio: float = 0.1
    ) -> Dict:
        """
        Perform standard randomized mutation testing on content.
        
        Flow:
        1. Identify all mutable fields (integers, booleans, key strings).
        2. Randomly select fields to mutate based on ratio.
        3. Run tests until time or iteration limit is reached.
        
        Args:
            original_content: original content object
            send_request: function to send request
            connectivity_check_func: connectivity check function
            save_failure_func: optional function to persist failures
            max_time_minutes: max test time in minutes (default 10)
            max_iterations: max test iterations (default 100)
            mutation_ratio: ratio of fields to mutate (default 0.1)
            
        Returns:
            dict: aggregated test result summary
        """
        import time
        import random
        
        # Record start time
        start_time = time.time()
        max_time_seconds = max_time_minutes * 60
        failure_sequences = []
        
        # Collect mutation candidates
        candidates = self.get_mutation_candidates(original_content)
        logger.info(f"Found {len(candidates['integers'])} integers, "
                  f"{len(candidates['booleans'])} booleans, "
                  f"{len(candidates['vdb_strings'])} VDB keywords, "
                  f"{len(candidates.get('float_arrays', []))} float-array placeholders to mutate")
        
        # Compute fields per mutation
        total_fields = len(candidates['integers']) + len(candidates['booleans']) + len(candidates['vdb_strings']) + len(candidates.get('float_arrays', []))
        if total_fields == 0:
            logger.warning("No mutable fields found")
            return {
                "iterations": 0,
                "failures": 0,
                "mutations": []
            }
        
        fields_per_mutation = max(1, int(total_fields * mutation_ratio))
        logger.debug(f"Will mutate {fields_per_mutation} fields per iteration")
        # Stats
        iteration_count = 0
        failures = 0
        failure_mutations = []
        time_based = max_time_minutes > 0
        
        logger.info(f"Starting randomized mutation testing: {'time-based' if time_based else 'iteration-based'}")
        logger.info(f"{'Max test time: ' + str(max_time_minutes) + ' minutes' if time_based else 'Max iterations: ' + str(max_iterations)}")
        
        # Main loop
        while True:
            # Check stop condition
            current_time = time.time()
            if (time_based and (current_time - start_time >= max_time_seconds)) or \
               (not time_based and iteration_count >= max_iterations):
                break
            iteration_count += 1
            
            # Prepare all candidate fields
            all_candidates = []
            # Integers
            for int_path, int_value in candidates['integers']:
                all_candidates.append(('integer', int_path, int_value, None))
            # Booleans
            for bool_path, bool_value in candidates['booleans']:
                all_candidates.append(('boolean', bool_path, bool_value, None))
            # Strings
            for string_path, string_value, keyword_type in candidates['vdb_strings']:
                all_candidates.append(('string', string_path, string_value, keyword_type))
            # Float array placeholders
            for array_path, dimension, is_multi_dim, dimensions in candidates.get('float_arrays', []):
                all_candidates.append(('float_array', array_path, dimension, {'is_multi_dim': is_multi_dim, 'dimensions': dimensions}))
                
            # Determine number of fields to mutate this iteration
            fields_to_mutate = max(1, int(len(all_candidates) * mutation_ratio))
            selected_fields = random.sample(all_candidates, min(fields_to_mutate, len(all_candidates)))
            
            # Apply mutations
            mutated_content = copy.deepcopy(original_content)
            mutation_details = []
            
            for field_type, field_path, field_value, keyword_type in selected_fields:
                if field_type == 'integer':
                    # Pick a random integer boundary value
                    new_value = random.choice(self.mutate_integer(field_value))
                    mutated_content = self.set_value_at_path(mutated_content, field_path, new_value)
                    mutation_details.append({
                        "type": "integer",
                        "path": field_path,
                        "original_value": field_value,
                        "mutated_value": new_value
                    })
                elif field_type == 'boolean':
                    # Flip boolean
                    new_value = not field_value
                    mutated_content = self.set_value_at_path(mutated_content, field_path, new_value)
                    mutation_details.append({
                        "type": "boolean",
                        "path": field_path,
                        "original_value": field_value,
                        "mutated_value": new_value
                    })
                elif field_type == 'string':
                    # Mutate strings with keyword type and context
                    string_mutations = self.mutate_string(field_value, keyword_type, field_path, original_content)
                    if string_mutations:  # Ensure we have candidates
                        new_value = random.choice(string_mutations)
                        mutated_content = self.set_value_at_path(mutated_content, field_path, new_value)
                        mutation_details.append({
                            "type": f"string_{keyword_type}",
                            "path": field_path,
                            "original_value": field_value,
                            "mutated_value": new_value
                        })
                elif field_type == 'float_array':
                    # Mutate dimensions for float-array placeholders
                    dimension = field_value
                    is_multi_dim = keyword_type.get('is_multi_dim', False)
                    dimensions = keyword_type.get('dimensions', [dimension])
                    
                    # Get candidate dimension mutations
                    dim_mutations = self.mutate_array_dimension(dimension, is_multi_dim, dimensions)
                    if dim_mutations:  # Ensure we have candidates
                        new_dim = random.choice(dim_mutations)
                        
                        # Build new placeholder
                        if is_multi_dim:
                            if isinstance(new_dim, list):
                                # Multi-dimensional array mutation
                                new_value = f"__FLOAT_MULTI_DIM_{','.join(map(str, new_dim))}__"
                            else:
                                # Downgrade to single-dimension array
                                new_value = f"__FLOAT_ARRAY_DIM_{new_dim}__"
                        else:
                            # Single-dimension array mutation
                            new_value = f"__FLOAT_ARRAY_DIM_{new_dim}__"
                        
                        mutated_content = self.set_value_at_path(mutated_content, field_path, new_value)
                        mutation_details.append({
                            "type": "float_array",
                            "path": field_path,
                            "original_dimension": dimensions if is_multi_dim else dimension,
                            "mutated_dimension": new_dim,
                            "is_multi_dim": is_multi_dim
                        })
            
            # Skip iteration if no mutations were applied
            if not mutation_details:
                continue
                
            # Send mutated request and check result
            try:
                # Compute and log mutation differences
                changes_summary = []
                for detail in mutation_details:
                    if 'mutated_dimension' in detail:
                        # Handle float-array dimension mutation
                        orig_dim = detail['original_dimension']
                        new_dim = detail['mutated_dimension']
                        dim_str = f"dimension {orig_dim} -> {new_dim}"
                        if detail.get('is_multi_dim', False) and isinstance(new_dim, list):
                            dim_str = f"dimension {orig_dim} -> {new_dim} (shape change)"
                        changes_summary.append(f"path '{'.'.join(map(str, detail['path']))}': {dim_str}")
                    else:
                        # Other mutation types
                        changes_summary.append(f"path '{'.'.join(map(str, detail['path']))}': {detail['original_value']} -> {detail['mutated_value']}")
                
                logger.info(f"Mutation summary #{iteration_count}: {'; '.join(changes_summary)}")
                response = send_request(mutated_content)
                
                # Check database connectivity
                if not connectivity_check_func():
                    logger.warning(f"Database connectivity issue detected! Mutation info: {mutation_details}")
                    failure_info = {
                        "mutation": mutation_details,
                        "content": mutated_content,
                        "response": getattr(response, 'text', str(response))
                    }
                    failure_sequences.append(failure_info)
                    
                    # Persist failure data if handler provided
                    if save_failure_func:
                        save_failure_func(failure_info)
                        
            except Exception as e:
                logger.error(f"Request send exception: {str(e)}, mutation info: {mutation_details}")
                
                # Build summary dict containing mutation details
                mutation_summary = {
                    "type": "combined",
                    "fields": len(mutation_details),
                    "details": mutation_details  # keep full mutation detail
                }
                
                failure_info = {
                    "mutation": mutation_summary,  # use summary dict instead of raw list
                    "content": mutated_content,
                    "error": str(e)
                }
                failure_mutations.append(failure_info)
                
                # Persist failure data if handler provided
                if save_failure_func:
                    save_failure_func(failure_info)
        
        total_time = (time.time() - start_time) / 60.0
        logger.info(f"Randomized mutation testing completed. Executed {iteration_count} iterations in {total_time:.2f} minutes")
        logger.info(f"Found {len(failure_sequences)} mutation sequences causing anomalies")
        
        return failure_sequences
        
    def exhaustive_mutate(
        self, 
        original_content: Dict, 
        send_request: Callable, 
        connectivity_check_func: Callable,
        save_failure_func: Callable = None
    ) -> List[Dict]:
        """
        Perform exhaustive mutation testing on content.
        
        Steps:
        1. Identify all integers, booleans, and key strings.
        2. For each integer, test all boundary values.
        3. For each boolean, test flipped values.
        4. For VDB keyword strings, apply targeted mutations.
        5. Combine mutations to increase coverage.
        
        Args:
            original_content: original content object
            send_request: function to send request
            connectivity_check_func: connectivity check function
            save_failure_func: function to save failure data
        
        Returns:
            list: mutation sequences that caused anomalies
        """
        # Get mutation candidates
        candidates = self.get_mutation_candidates(original_content)
        logger.info(f"Found {len(candidates['integers'])} integers, {len(candidates['booleans'])} booleans, {len(candidates['vdb_strings'])} VDB keywords to mutate")
        
        # Store discovered failure sequences
        failure_sequences = []
        
        # Test all integer mutations
        def test_integer_mutations(content, context=""):
            for int_path, int_value in candidates['integers']:
                for mutated_value in self.mutate_integer(int_value):
                    # Skip original value
                    if mutated_value == int_value:
                        continue
                        
                    mutated_content = self.set_value_at_path(
                        content, int_path, mutated_value
                    )
                    
                    mutation_info = {
                        "path": int_path,
                        "original_value": int_value,
                        "mutated_value": mutated_value,
                        "type": "integer",
                        "context": context
                    }
                    
                    logger.debug(f"Testing integer mutation: {mutation_info}")
                    
                    # Send mutation request
                    try:
                        response = send_request(mutated_content)
                        
                        # Check database connectivity
                        if not connectivity_check_func():
                            logger.warning(f"Database connectivity issue detected! Mutation info: {mutation_info}")
                            failure_info = {
                                "mutation": mutation_info,
                                "content": mutated_content,
                                "response": getattr(response, 'text', str(response))
                            }
                            failure_sequences.append(failure_info)
                            
                            # Persist failure data if handler provided
                            if save_failure_func:
                                save_failure_func(failure_info)
                                
                    except Exception as e:
                        logger.error(f"Request send exception: {str(e)}, mutation info: {mutation_info}")
                        
                        failure_info = {
                            "mutation": mutation_info,
                            "content": mutated_content,
                            "error": str(e)
                        }
                        failure_sequences.append(failure_info)
                        
                        # Persist failure data if handler provided
                        if save_failure_func:
                            save_failure_func(failure_info)
        
        # Test string mutations
        def test_string_mutations(content, context=""):
            """Test string mutations"""
            for string_path, string_value, keyword_type in candidates['vdb_strings']:
                # Get mutation values for the keyword type
                mutations = self.mutate_string(string_value, keyword_type)
                
                for mutated_string in mutations:
                    # Create mutated content
                    try:
                        string_mutated_content = self.set_value_at_path(
                            copy.deepcopy(content), string_path, mutated_string
                        )
                        
                        mutation_info = {
                            "path": string_path,
                            "original_value": string_value,
                            "mutated_value": mutated_string,
                            "type": f"string_{keyword_type}"
                        }
                        
                        logger.debug(f"Testing string mutation {context}: {mutation_info}")
                        
                        # Send mutation request
                        try:
                            response = send_request(string_mutated_content)
                            
                            # Check database connectivity
                            if not connectivity_check_func():
                                logger.warning(f"Database connectivity issue detected! Mutation info: {mutation_info}")
                                failure_info = {
                                    "mutation": mutation_info,
                                    "content": string_mutated_content,
                                    "response": getattr(response, 'text', str(response))
                                }
                                failure_sequences.append(failure_info)
                                
                                # Persist failure data if handler provided
                                if save_failure_func:
                                    save_failure_func(failure_info)
                        except Exception as e:
                            logger.error(f"Request send exception: {str(e)}, mutation info: {mutation_info}")
                            
                            failure_info = {
                                "mutation": mutation_info,
                                "content": string_mutated_content,
                                "error": str(e)
                            }
                            failure_sequences.append(failure_info)
                            
                            # Persist failure data if handler provided
                            if save_failure_func:
                                save_failure_func(failure_info)
                    except Exception as e:
                        logger.error(f"Error setting path value {string_path}: {str(e)}")
        
        # First test all integer mutations
        logger.info("Start testing integer mutations...")
        test_integer_mutations(original_content, "initial_integer_test")
        
        # Test string mutations
        if candidates['vdb_strings']:
            logger.info(f"Start testing string mutations...({len(candidates['vdb_strings'])} keywords)")
            test_string_mutations(original_content, "initial_string_test")
        
        # Then mutate each boolean and retest integers and strings
        logger.info("Start testing boolean mutations and combination mutations...")
        for bool_path, bool_value in candidates['booleans']:
            for mutated_bool in self.mutate_boolean(bool_value):
                # Skip original value
                if mutated_bool == bool_value:
                    continue
                    
                bool_mutated_content = self.set_value_at_path(
                    original_content, bool_path, mutated_bool
                )
                
                mutation_info = {
                    "path": bool_path,
                    "original_value": bool_value,
                    "mutated_value": mutated_bool,
                    "type": "boolean"
                }
                
                logger.debug(f"Testing boolean mutation: {mutation_info}")
                
                # Send mutation request
                try:
                    response = send_request(bool_mutated_content)
                    
                    # Check database connectivity
                    if not connectivity_check_func():
                        logger.warning(f"Database connectivity issue detected! Mutation info: {mutation_info}")
                        failure_info = {
                            "mutation": mutation_info,
                            "content": bool_mutated_content,
                            "response": getattr(response, 'text', str(response))
                        }
                        failure_sequences.append(failure_info)
                        
                        # Persist failure data if handler provided
                        if save_failure_func:
                            save_failure_func(failure_info)
                            
                    # After boolean mutation, retest all integer mutations
                    context = f"after_bool_mutation_{bool_path}"
                    test_integer_mutations(bool_mutated_content, context)
                    
                    # After boolean mutation, test string mutations
                    if candidates['vdb_strings']:
                        test_string_mutations(bool_mutated_content, f"after_bool_{bool_path}")
                    
                except Exception as e:
                    logger.error(f"Request send exception: {str(e)}, mutation info: {mutation_info}")
                    
                    failure_info = {
                        "mutation": mutation_info,
                        "content": bool_mutated_content,
                        "error": str(e)
                    }
                    failure_sequences.append(failure_info)
                    
                    # Persist failure data if handler provided
                    if save_failure_func:
                        save_failure_func(failure_info)
        
        logger.info(f"Exhaustive mutation testing completed. Found {len(failure_sequences)} mutation sequences causing anomalies")
        return failure_sequences
