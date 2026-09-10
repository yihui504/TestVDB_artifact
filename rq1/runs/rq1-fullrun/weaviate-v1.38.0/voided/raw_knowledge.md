> # weaviate v1.38.0 raw_knowledge
> ⚠️ KNOWLEDGE_DEGRADED（Task 4a，extractor 400 第 5 次）：v1.38.0 spec 骨架 + v1.37.4 概念/源码参数块复用（同 1.3x 系列）+ v1.38.0 源码参数核对。

## Spec-derived Endpoints (108 entries)

#### List available endpoints
- Method: GET
- Path: /
- Source URL: openapi (Step 6b cross-check fallback)
- Description: Get links to other endpoints to help discover the REST API.
- Path Params: none

#### List aliases
- Method: GET
- Path: /aliases
- Source URL: openapi (Step 6b cross-check fallback)
- Description: Retrieve a list of all aliases in the system. Results can be filtered by specifying a collection (class) name to get aliases for a specific collection only.
- Path Params: class

#### Create a new alias
- Method: POST
- Path: /aliases
- Source URL: openapi (Step 6b cross-check fallback)
- Description: Create a new alias mapping between an alias name and a collection (class). The alias acts as an alternative name for accessing the collection.
- Path Params: body

#### Get an alias
- Method: GET
- Path: /aliases/{aliasName}
- Source URL: openapi (Step 6b cross-check fallback)
- Description: Retrieve details about a specific alias by its name, including which collection (class) it points to.
- Path Params: aliasName

#### Update an alias
- Method: PUT
- Path: /aliases/{aliasName}
- Source URL: openapi (Step 6b cross-check fallback)
- Description: Update an existing alias to point to a different collection (class). This allows you to redirect an alias from one collection to another without changing the alias name.
- Path Params: aliasName, body

#### Delete an alias
- Method: DELETE
- Path: /aliases/{aliasName}
- Source URL: openapi (Step 6b cross-check fallback)
- Description: Remove an existing alias from the system. This will delete the alias mapping but will not affect the underlying collection (class).
- Path Params: aliasName

#### List all groups of a specific type
- Method: GET
- Path: /authz/groups/{groupType}
- Source URL: openapi (Step 6b cross-check fallback)
- Description: Retrieves a list of all available group names for a specified group type (`oidc` or `db`).
- Path Params: groupType

#### Assign a role to a group
- Method: POST
- Path: /authz/groups/{id}/assign
- Source URL: openapi (Step 6b cross-check fallback)
- Description: Assign roles to the specified group.
- Path Params: id, body

#### Revoke a role from a group
- Method: POST
- Path: /authz/groups/{id}/revoke
- Source URL: openapi (Step 6b cross-check fallback)
- Description: Revoke roles from the specified group.
- Path Params: id, body

#### Get roles assigned to a specific group
- Method: GET
- Path: /authz/groups/{id}/roles/{groupType}
- Source URL: openapi (Step 6b cross-check fallback)
- Description: Retrieves a list of all roles assigned to a specific group. The group must be identified by both its name (`id`) and its type (`db` or `oidc`).
- Path Params: id, groupType, includeFullRoles

#### Get all roles
- Method: GET
- Path: /authz/roles
- Source URL: openapi (Step 6b cross-check fallback)
- Description: Get all roles and their assigned permissions.
- Path Params: none

#### Create new role
- Method: POST
- Path: /authz/roles
- Source URL: openapi (Step 6b cross-check fallback)
- Description: Create a new role with the specified permissions.
- Path Params: body

#### Get a role
- Method: GET
- Path: /authz/roles/{id}
- Source URL: openapi (Step 6b cross-check fallback)
- Description: Fetch a role by its name.
- Path Params: id

#### Delete a role
- Method: DELETE
- Path: /authz/roles/{id}
- Source URL: openapi (Step 6b cross-check fallback)
- Description: Deleting a role will remove it from the system, and revoke the associated permissions from all users who had this role.
- Path Params: id

#### Add permissions to a role
- Method: POST
- Path: /authz/roles/{id}/add-permissions
- Source URL: openapi (Step 6b cross-check fallback)
- Description: Add new permissions to an existing role without affecting current permissions.
- Path Params: id, body

#### Get groups that have a specific role assigned
- Method: GET
- Path: /authz/roles/{id}/group-assignments
- Source URL: openapi (Step 6b cross-check fallback)
- Description: Retrieves a list of all groups that have been assigned a specific role, identified by its name.
- Path Params: id

#### Check whether a role possesses a permission
- Method: POST
- Path: /authz/roles/{id}/has-permission
- Source URL: openapi (Step 6b cross-check fallback)
- Description: Check whether a role has the specified permissions.
- Path Params: id, body

#### Remove permissions from a role
- Method: POST
- Path: /authz/roles/{id}/remove-permissions
- Source URL: openapi (Step 6b cross-check fallback)
- Description: Permissions can be revoked from a specified role. Removing all permissions from a role will delete the role itself.
- Path Params: id, body

#### Get users assigned to a role
- Method: GET
- Path: /authz/roles/{id}/user-assignments
- Source URL: openapi (Step 6b cross-check fallback)
- Description: Fetch a list of users which have the specified role.
- Path Params: id

#### Get users assigned to a role
- Method: GET
- Path: /authz/roles/{id}/users
- Source URL: openapi (Step 6b cross-check fallback)
- Description: Get all the users (`db` + `oidc`) who have been assigned a specific role. Deprecated, will be removed when v1.29 is not supported anymore.
- Path Params: id

#### Assign a role to a user
- Method: POST
- Path: /authz/users/{id}/assign
- Source URL: openapi (Step 6b cross-check fallback)
- Description: Assign one or more roles to a user. Users can have multiple roles.
- Path Params: id, body

#### Revoke a role from a user
- Method: POST
- Path: /authz/users/{id}/revoke
- Source URL: openapi (Step 6b cross-check fallback)
- Description: Remove one or more roles from a user.
- Path Params: id, body

#### Get roles assigned to a user
- Method: GET
- Path: /authz/users/{id}/roles
- Source URL: openapi (Step 6b cross-check fallback)
- Description: Retrieve the roles assigned to a specific user (`db` + `oidc`). Deprecated, will be removed when 1.29 is not supported anymore
- Path Params: id

#### Get roles assigned to a user
- Method: GET
- Path: /authz/users/{id}/roles/{userType}
- Source URL: openapi (Step 6b cross-check fallback)
- Description: Get all the roles for a specific user (`db` or `oidc`).
- Path Params: id, userType, includeFullRoles

#### Create a backup
- Method: POST
- Path: /backups/{backend}
- Source URL: openapi (Step 6b cross-check fallback)
- Description: Initiates the creation of a backup for specified collections on a designated backend storage.<br/><br/>Notes:<br/>- Backups are compressed using gzip by default.<br/>- Weaviate remains operational during the backup process.
- Path Params: backend, body

#### List all created backups
- Method: GET
- Path: /backups/{backend}
- Source URL: openapi (Step 6b cross-check fallback)
- Description: List all created backups IDs, Status
- Path Params: backend, order

#### Get backup creation status
- Method: GET
- Path: /backups/{backend}/{id}
- Source URL: openapi (Step 6b cross-check fallback)
- Description: Checks the status of a specific backup creation process identified by its ID on the specified backend.<br/><br/>Client libraries often provide a 'wait for completion' feature that polls this endpoint automatically. Use this endpoint for manual status checks or if 'wait for completion' is disabled.
- Path Params: backend, id, bucket, path

#### Cancel a backup
- Method: DELETE
- Path: /backups/{backend}/{id}
- Source URL: openapi (Step 6b cross-check fallback)
- Description: Cancels an ongoing backup operation identified by its ID.
- Path Params: backend, id, bucket, path

#### Restore from a backup
- Method: POST
- Path: /backups/{backend}/{id}/restore
- Source URL: openapi (Step 6b cross-check fallback)
- Description: Initiates the restoration of collections from a specified backup located on a designated backend.<br/><br/>Requirements:<br/>- Target cluster must have the same number of nodes as the source cluster where the backup was created.<br/>- Collections included in the restore must not already exist on the target cluster.<br/>- Node names must match between the backup and the target cluster.
- Path Params: backend, id, body

#### Get backup restoration status
- Method: GET
- Path: /backups/{backend}/{id}/restore
- Source URL: openapi (Step 6b cross-check fallback)
- Description: Checks the status of a specific backup restoration process identified by the backup ID on the specified backend.<br/><br/>Client libraries often provide a 'wait for completion' feature that polls this endpoint automatically. Use this endpoint for manual status checks or if 'wait for completion' is disabled.
- Path Params: backend, id, bucket, path

#### Cancel a backup restoration
- Method: DELETE
- Path: /backups/{backend}/{id}/restore
- Source URL: openapi (Step 6b cross-check fallback)
- Description: Cancels an ongoing backup restoration process identified by its ID on the specified backend storage.
- Path Params: backend, id, bucket, path

#### Create objects in batch
- Method: POST
- Path: /batch/objects
- Source URL: openapi (Step 6b cross-check fallback)
- Description: Registers multiple data objects in a single request for efficiency. Metadata and schema values for each object are validated.<br/><br/>**Note (idempotence)**:<br/>This operation is idempotent based on the object UUIDs provided. If an object with a given UUID already exists, it will be overwritten (similar to a PUT operation for that specific object within the batch).
- Path Params: body, ?

#### Delete objects in batch
- Method: DELETE
- Path: /batch/objects
- Source URL: openapi (Step 6b cross-check fallback)
- Description: Removes multiple data objects based on a filter specified in the request body.<br/><br/>Deletion occurs based on the filter criteria provided in the `where` clause. There is a configurable limit (default 10,000, set via `QUERY_MAXIMUM_RESULTS`) on how many objects can be deleted in a single batch request to prevent excessive resource usage. Objects are deleted in the order they match the filter. T
- Path Params: body, ?, ?

#### Create cross-references in bulk
- Method: POST
- Path: /batch/references
- Source URL: openapi (Step 6b cross-check fallback)
- Description: Batch create cross-references between collection items in bulk.
- Path Params: body, ?

#### Start a classification
- Method: POST
- Path: /classifications/
- Source URL: openapi (Step 6b cross-check fallback)
- Description: Initiates a background classification task based on the provided parameters. Use the GET /classifications/{id} endpoint to monitor the status and retrieve results.
- Path Params: params

#### Get classification status
- Method: GET
- Path: /classifications/{id}
- Source URL: openapi (Step 6b cross-check fallback)
- Description: Retrieves the status, metadata, and results (if completed) of a classification task identified by its unique ID.
- Path Params: id

#### Get cluster statistics
- Method: GET
- Path: /cluster/statistics
- Source URL: openapi (Step 6b cross-check fallback)
- Description: Provides statistics about the internal Raft consensus protocol state for the Weaviate cluster.
- Path Params: none

#### Start a new export
- Method: POST
- Path: /export/{backend}
- Source URL: openapi (Step 6b cross-check fallback)
- Description: Initiates an export operation on the specified backend storage (S3, GCS, Azure, or filesystem). The output format is controlled by the required 'file_format' field in the request body (currently only 'parquet' is supported). Each collection is exported to a separate file.
- Path Params: backend, body

#### Get export status
- Method: GET
- Path: /export/{backend}/{id}
- Source URL: openapi (Step 6b cross-check fallback)
- Description: Retrieves the current status of an export operation, including progress for each collection being exported.
- Path Params: backend, id

#### Cancel an export
- Method: DELETE
- Path: /export/{backend}/{id}
- Source URL: openapi (Step 6b cross-check fallback)
- Description: Cancels an ongoing export operation identified by its ID.
- Path Params: backend, id

#### Perform a GraphQL query
- Method: POST
- Path: /graphql
- Source URL: openapi (Step 6b cross-check fallback)
- Description: Executes a single GraphQL query provided in the request body. Use this endpoint for all Weaviate data queries and exploration.
- Path Params: body

#### Perform batched GraphQL queries
- Method: POST
- Path: /graphql/batch
- Source URL: openapi (Step 6b cross-check fallback)
- Description: Executes multiple GraphQL queries provided in the request body as an array. Allows performing several queries in a single network request for efficiency.
- Path Params: body

#### MCP Streamable HTTP endpoint. Handles JSON-RPC requests for tool discovery and invocation.
- Method: POST
- Path: /mcp
- Source URL: openapi (Step 6b cross-check fallback)
- Description: MCP Streamable HTTP endpoint. Handles JSON-RPC requests for tool discovery and invocation.
- Path Params: none

#### Opens an SSE stream for receiving MCP server-sent events.
- Method: GET
- Path: /mcp
- Source URL: openapi (Step 6b cross-check fallback)
- Description: Opens an SSE stream for receiving MCP server-sent events.
- Path Params: none

#### Terminates an MCP session.
- Method: DELETE
- Path: /mcp
- Source URL: openapi (Step 6b cross-check fallback)
- Description: Terminates an MCP session.
- Path Params: none

#### Get instance metadata
- Method: GET
- Path: /meta
- Source URL: openapi (Step 6b cross-check fallback)
- Description: Provides meta-information about the running Weaviate instance, including its version, loaded modules, and network hostname. This information can be useful for monitoring, compatibility checks, or inter-instance communication.
- Path Params: none

#### List namespaces
- Method: GET
- Path: /namespaces
- Source URL: openapi (Step 6b cross-check fallback)
- Description: Retrieve the list of all namespaces the caller has permission to see. Callers without any applicable `manage_namespaces` permission receive an empty list (never 403).
- Path Params: none

#### Create a new namespace
- Method: POST
- Path: /namespaces/{namespace_id}
- Source URL: openapi (Step 6b cross-check fallback)
- Description: Create a new cluster-level namespace with the given name. Names must contain only lowercase letters, digits, and hyphens, must start and end with a letter or digit, must be 3-36 characters long, and must not be a reserved name.
- Path Params: namespace_id, body

#### Get a namespace
- Method: GET
- Path: /namespaces/{namespace_id}
- Source URL: openapi (Step 6b cross-check fallback)
- Description: Retrieve details about a specific namespace by its name.
- Path Params: namespace_id

#### Update a namespace
- Method: PUT
- Path: /namespaces/{namespace_id}
- Source URL: openapi (Step 6b cross-check fallback)
- Description: Update a namespace's `home_node`. The new value applies to future placement decisions only (new collection create, new tenant create, tenant reactivation). Existing live shards are not moved.
- Path Params: namespace_id, body

#### Delete a namespace
- Method: DELETE
- Path: /namespaces/{namespace_id}
- Source URL: openapi (Step 6b cross-check fallback)
- Description: Mark a namespace for deletion. The endpoint is asynchronous: the namespace is flipped to the "deleting" state and its dynamic users are removed synchronously; classes and aliases are torn down by the leader on a periodic cleanup tick. Repeated calls while the namespace is still in the "deleting" state are idempotent and return 202.
- Path Params: namespace_id

#### Get node status
- Method: GET
- Path: /nodes
- Source URL: openapi (Step 6b cross-check fallback)
- Description: Retrieves status information about all nodes in the cluster. Use the `output` query parameter to control the level of detail.
- Path Params: ?

#### Get node status by collection
- Method: GET
- Path: /nodes/{className}
- Source URL: openapi (Step 6b cross-check fallback)
- Description: Retrieves status information only for the nodes that host shards for the specified collection (`className`). Use the `output` query parameter to control the level of detail.
- Path Params: className, shardName, ?

#### List objects
- Method: GET
- Path: /objects
- Source URL: openapi (Step 6b cross-check fallback)
- Description: Retrieves a list of data objects. By default, objects are returned in reverse order of creation. Requires a collection name (`class`) parameter to specify which collection's objects to list, otherwise, returns an empty list.
- Path Params: ?, ?, ?, ?, ?, ?, ?, ?

#### Create an object
- Method: POST
- Path: /objects
- Source URL: openapi (Step 6b cross-check fallback)
- Description: Creates a new data object. The object's metadata and schema values are validated before creation.<br/><br/>**Note (batch import)**:<br/>If you plan on importing a large number of objects, using the `/batch/objects` endpoint is significantly more efficient than sending multiple single requests.<br/><br/>**Note (idempotence)**:<br/>This operation (POST) fails if an object with the provided ID alread
- Path Params: body, ?

#### Validate an object
- Method: POST
- Path: /objects/validate
- Source URL: openapi (Step 6b cross-check fallback)
- Description: Checks if a data object's structure conforms to the specified collection schema and metadata rules without actually storing the object.<br/><br/>A successful validation returns a 200 OK status code with no body. If validation fails, an error response with details is returned.
- Path Params: body

#### Get an object
- Method: GET
- Path: /objects/{className}/{id}
- Source URL: openapi (Step 6b cross-check fallback)
- Description: Get a data object based on its collection name (`className`) and UUID (`id`).
- Path Params: className, id, ?, ?, ?, ?

#### Delete an object
- Method: DELETE
- Path: /objects/{className}/{id}
- Source URL: openapi (Step 6b cross-check fallback)
- Description: Removes a data object from a specific collection, identified by its collection name (`className`) and UUID (`id`).<br/><br/>**Note on deleting references (legacy format):**<br/>For backward compatibility with older beacon formats (lacking a collection name), deleting a reference requires the beacon in the request to exactly match the stored format. Beacons always use `localhost` as the host, indic
- Path Params: className, id, ?, ?

#### Replace an object
- Method: PUT
- Path: /objects/{className}/{id}
- Source URL: openapi (Step 6b cross-check fallback)
- Description: Replaces properties of an existing data object. The object is identified by its collection name (`className`) and UUID (`id`). The request body must contain the complete object definition with the new property values.
- Path Params: className, id, body, ?

#### Patch an object
- Method: PATCH
- Path: /objects/{className}/{id}
- Source URL: openapi (Step 6b cross-check fallback)
- Description: Updates specific properties of an existing data object using JSON merge patch semantics (RFC 7396). The object is identified by its collection name (`className`) and UUID (`id`). Only the fields provided in the request body are modified. Metadata and schema values are validated, and the object's `lastUpdateTimeUnix` is updated.
- Path Params: className, id, body, ?

#### Add an object reference
- Method: POST
- Path: /objects/{className}/{id}/references/{propertyName}
- Source URL: openapi (Step 6b cross-check fallback)
- Description: Adds a new reference to a reference property (`propertyName`) on a source data object. The source object is identified by its collection name (`className`) and UUID (`id`). The reference to add is specified in the request body.
- Path Params: className, id, propertyName, body, ?, ?

#### Replace object references
- Method: PUT
- Path: /objects/{className}/{id}/references/{propertyName}
- Source URL: openapi (Step 6b cross-check fallback)
- Description: Replaces all existing references for a specific reference property (`propertyName`) on a source data object. The source object is identified by its collection name (`className`) and UUID (`id`). The new set of references is provided in the request body.
- Path Params: className, id, propertyName, body, ?, ?

#### Delete an object reference
- Method: DELETE
- Path: /objects/{className}/{id}/references/{propertyName}
- Source URL: openapi (Step 6b cross-check fallback)
- Description: Removes a specific reference from a reference property (`propertyName`) of a source data object. The source object is identified by its collection name (`className`) and UUID (`id`). The reference to remove is specified in the request body.
- Path Params: className, id, propertyName, body, ?, ?

#### Delete an object
- Method: DELETE
- Path: /objects/{id}
- Source URL: openapi (Step 6b cross-check fallback)
- Description: Deletes an object from the database based on its UUID. <br/><br/>**Note**: This endpoint is deprecated and will be removed in a future version. Use the `/objects/{className}/{id}` endpoint instead.
- Path Params: id, ?, ?

#### Get an object
- Method: GET
- Path: /objects/{id}
- Source URL: openapi (Step 6b cross-check fallback)
- Description: Get a specific object based on its UUID. Also available as Websocket bus. <br/><br/>**Note**: This endpoint is deprecated and will be removed in a future version. Use the `/objects/{className}/{id}` endpoint instead.
- Path Params: id, ?

#### Patch an object
- Method: PATCH
- Path: /objects/{id}
- Source URL: openapi (Step 6b cross-check fallback)
- Description: Update an object based on its UUID (using patch semantics). This method supports json-merge style patch semantics (RFC 7396). Provided meta-data and schema values are validated. `lastUpdateTimeUnix` is set to the time this function is called. <br/><br/>**Note**: This endpoint is deprecated and will be removed in a future version. Use the `/objects/{className}/{id}` endpoint instead.
- Path Params: id, body, ?

#### Update an object
- Method: PUT
- Path: /objects/{id}
- Source URL: openapi (Step 6b cross-check fallback)
- Description: Updates an object based on its UUID. Given meta-data and schema values are validated. `lastUpdateTimeUnix` is set to the time this function is called. <br/><br/>**Note**: This endpoint is deprecated and will be removed in a future version. Use the `/objects/{className}/{id}` endpoint instead.
- Path Params: id, body, ?

#### Add an object reference
- Method: POST
- Path: /objects/{id}/references/{propertyName}
- Source URL: openapi (Step 6b cross-check fallback)
- Description: Add a reference to a specific property of a data object. <br/><br/>**Note**: This endpoint is deprecated and will be removed in a future version. Use the `/objects/{className}/{id}/references/{propertyName}` endpoint instead.
- Path Params: id, propertyName, body, ?

#### Replace object references
- Method: PUT
- Path: /objects/{id}/references/{propertyName}
- Source URL: openapi (Step 6b cross-check fallback)
- Description: Replace all references in cross-reference property of an object. <br/><br/>**Note**: This endpoint is deprecated and will be removed in a future version. Use the `/objects/{className}/{id}/references/{propertyName}` endpoint instead.
- Path Params: id, propertyName, body, ?

#### Delete an object reference
- Method: DELETE
- Path: /objects/{id}/references/{propertyName}
- Source URL: openapi (Step 6b cross-check fallback)
- Description: Delete the single reference that is given in the body from the list of references that this property has. <br/><br/>**Note**: This endpoint is deprecated and will be removed in a future version. Use the `/objects/{className}/{id}/references/{propertyName}` endpoint instead.
- Path Params: id, propertyName, body, ?

#### Initiate a replica movement
- Method: POST
- Path: /replication/replicate
- Source URL: openapi (Step 6b cross-check fallback)
- Description: Begins an asynchronous operation to move or copy a specific shard replica from its current node to a designated target node. The operation involves copying data, synchronizing, and potentially decommissioning the source replica.
- Path Params: body

#### Delete all replication operations
- Method: DELETE
- Path: /replication/replicate
- Source URL: openapi (Step 6b cross-check fallback)
- Description: Schedules all replication operations for deletion across all collections, shards, and nodes.
- Path Params: none

#### Force delete replication operations
- Method: POST
- Path: /replication/replicate/force-delete
- Source URL: openapi (Step 6b cross-check fallback)
- Description: USE AT OWN RISK! Synchronously force delete operations from the FSM. This will not perform any checks on which state the operation is in so may lead to data corruption or loss. It is recommended to first scale the number of replication engine workers to 0 before calling this endpoint to ensure no operations are in-flight.
- Path Params: body

#### List replication operations
- Method: GET
- Path: /replication/replicate/list
- Source URL: openapi (Step 6b cross-check fallback)
- Description: Retrieves a list of currently registered replication operations, optionally filtered by collection, shard, or node ID.
- Path Params: targetNode, collection, shard, includeHistory

#### Retrieve a replication operation
- Method: GET
- Path: /replication/replicate/{id}
- Source URL: openapi (Step 6b cross-check fallback)
- Description: Fetches the current status and detailed information for a specific replication operation, identified by its unique ID. Optionally includes historical data of the operation's progress if requested.
- Path Params: id, includeHistory

#### Delete a replication operation
- Method: DELETE
- Path: /replication/replicate/{id}
- Source URL: openapi (Step 6b cross-check fallback)
- Description: Removes a specific replication operation. If the operation is currently active, it will be cancelled and its resources cleaned up before the operation is deleted.
- Path Params: id

#### Cancel a replication operation
- Method: POST
- Path: /replication/replicate/{id}/cancel
- Source URL: openapi (Step 6b cross-check fallback)
- Description: Requests the cancellation of an active replication operation identified by its ID. The operation will be stopped, but its record will remain in the `CANCELLED` state (can't be resumed) and will not be automatically deleted.
- Path Params: id

#### Get replication scale plan
- Method: GET
- Path: /replication/scale
- Source URL: openapi (Step 6b cross-check fallback)
- Description: Computes and returns a replication scale plan for a given collection and desired replication factor. The plan includes, for each shard, a list of nodes to be added and a list of nodes to be removed.
- Path Params: collection, replicationFactor

#### Apply replication scaling plan
- Method: POST
- Path: /replication/scale
- Source URL: openapi (Step 6b cross-check fallback)
- Description: Apply a replication scaling plan that specifies nodes to add or remove per shard for a given collection.
- Path Params: body

#### Get sharding state
- Method: GET
- Path: /replication/sharding-state
- Source URL: openapi (Step 6b cross-check fallback)
- Description: Fetches the current sharding state, including replica locations and statuses, for all collections or a specified collection. If a shard name is provided along with a collection, the state for that specific shard is returned.
- Path Params: collection, shard

#### Get all collection definitions
- Method: GET
- Path: /schema
- Source URL: openapi (Step 6b cross-check fallback)
- Description: Retrieves the definitions of all collections (classes) currently in the database schema.
- Path Params: consistency

#### Create a new collection
- Method: POST
- Path: /schema
- Source URL: openapi (Step 6b cross-check fallback)
- Description: Defines and creates a new collection (class).<br/><br/>If [`AutoSchema`](https://docs.weaviate.io/weaviate/config-refs/collections#auto-schema) is enabled (not recommended for production), Weaviate might attempt to infer schema from data during import. Manual definition via this endpoint provides explicit control.
- Path Params: objectClass

#### Get a single collection
- Method: GET
- Path: /schema/{className}
- Source URL: openapi (Step 6b cross-check fallback)
- Description: Retrieve the definition of a specific collection (`className`), including its properties, configuration, and vectorizer settings.
- Path Params: className, consistency

#### Delete a collection (and all associated data)
- Method: DELETE
- Path: /schema/{className}
- Source URL: openapi (Step 6b cross-check fallback)
- Description: Removes a collection definition from the schema. WARNING: This action permanently deletes all data objects stored within the collection.
- Path Params: className

#### Update collection definition
- Method: PUT
- Path: /schema/{className}
- Source URL: openapi (Step 6b cross-check fallback)
- Description: Updates the configuration settings of an existing collection (`className`) based on the provided definition. Note: This operation modifies mutable settings specified in the request body. It does not add properties (use `POST /schema/{className}/properties` for that) or change the collection name.
- Path Params: className, objectClass

#### Get index status for all properties of a collection
- Method: GET
- Path: /schema/{className}/indexes
- Source URL: openapi (Step 6b cross-check fallback)
- Description: Returns per-property index state including active reindex progress. This powers the UI to show live migration status.
- Path Params: className

#### Update index configuration for a property (triggers reindex)
- Method: PUT
- Path: /schema/{className}/indexes/{propertyName}
- Source URL: openapi (Step 6b cross-check fallback)
- Description: Declaratively sets the desired index state for a property. The system computes the diff from the current state and triggers the appropriate reindex task.
- Path Params: className, propertyName, tenants, body

#### Add a property to a collection
- Method: POST
- Path: /schema/{className}/properties
- Source URL: openapi (Step 6b cross-check fallback)
- Description: Adds a new property definition to an existing collection (`className`) definition.
- Path Params: className, body

#### Delete a property's inverted index
- Method: DELETE
- Path: /schema/{className}/properties/{propertyName}/index/{indexName}
- Source URL: openapi (Step 6b cross-check fallback)
- Description: Deletes an inverted index of a specific property within a collection (`className`). The index to delete is identified by `indexName` and must be one of `filterable`, `searchable`, or `rangeFilters`.
- Path Params: className, propertyName, indexName

#### Tokenize text using a property's configuration
- Method: POST
- Path: /schema/{className}/properties/{propertyName}/tokenize
- Source URL: openapi (Step 6b cross-check fallback)
- Description: Tokenizes the provided text using the tokenization method configured for the specified property. This endpoint automatically applies the property's tokenization setting and the collection's stopword configuration, making it useful for understanding exactly how text will be processed for a given property during indexing and querying.
- Path Params: className, propertyName, body

#### Get the shards status of a collection
- Method: GET
- Path: /schema/{className}/shards
- Source URL: openapi (Step 6b cross-check fallback)
- Description: Retrieves the status of all shards associated with the specified collection (`className`). For multi-tenant collections, use the `tenant` query parameter to retrieve status for a specific tenant's shards.
- Path Params: className, tenant

#### Update a shard status
- Method: PUT
- Path: /schema/{className}/shards/{shardName}
- Source URL: openapi (Step 6b cross-check fallback)
- Description: Updates the status of a specific shard within a collection (e.g., sets it to `READY` or `READONLY`). This is typically used after resolving an underlying issue (like disk space) that caused a shard to become non-operational. There is also a convenience function in each client to set the status of all shards of a collection.
- Path Params: className, shardName, body

#### Create a new tenant
- Method: POST
- Path: /schema/{className}/tenants
- Source URL: openapi (Step 6b cross-check fallback)
- Description: Creates one or more new tenants for a specified collection (`className`). Multi-tenancy must be enabled for the collection via its definition.
- Path Params: className, body

#### Update a tenant
- Method: PUT
- Path: /schema/{className}/tenants
- Source URL: openapi (Step 6b cross-check fallback)
- Description: Updates the activity status (e.g., `ACTIVE`, `INACTIVE`, etc.) of one or more specified tenants within a collection (`className`).
- Path Params: className, body

#### Delete tenants
- Method: DELETE
- Path: /schema/{className}/tenants
- Source URL: openapi (Step 6b cross-check fallback)
- Description: Deletes one or more specified tenants from a collection (`className`). WARNING: This action permanently deletes all data associated with the specified tenants.
- Path Params: className, tenants

#### Get the list of tenants
- Method: GET
- Path: /schema/{className}/tenants
- Source URL: openapi (Step 6b cross-check fallback)
- Description: Retrieves a list of all tenants currently associated with the specified collection.
- Path Params: className, consistency

#### Get a specific tenant
- Method: GET
- Path: /schema/{className}/tenants/{tenantName}
- Source URL: openapi (Step 6b cross-check fallback)
- Description: Retrieves details about a specific tenant within the given collection (`className`), such as its current activity status.
- Path Params: className, tenantName, consistency

#### Delete a collection's vector index.
- Method: DELETE
- Path: /schema/{className}/vectors/{vectorIndexName}/index
- Source URL: openapi (Step 6b cross-check fallback)
- Description: Deletes a specific vector index within a collection (`className`). The vector index to delete is identified by `vectorIndexName`.
- Path Params: className, vectorIndexName

#### Lists all distributed tasks in the cluster
- Method: GET
- Path: /tasks
- Source URL: openapi (Step 6b cross-check fallback)
- Description: N/A
- Path Params: none

#### Tokenize text
- Method: POST
- Path: /tokenize
- Source URL: openapi (Step 6b cross-check fallback)
- Description: Tokenizes the provided text using the specified tokenization method. This is a stateless utility endpoint useful for debugging and understanding how text will be processed during indexing and querying. The response includes both the indexed tokens (as stored in the inverted index) and query tokens (after optional stopword removal).
- Path Params: body

#### List all users
- Method: GET
- Path: /users/db
- Source URL: openapi (Step 6b cross-check fallback)
- Description: Retrieves a list of all database (`db` user type) users with their roles and status information.
- Path Params: includeLastUsedTime

#### Get user info
- Method: GET
- Path: /users/db/{user_id}
- Source URL: openapi (Step 6b cross-check fallback)
- Description: Retrieve detailed information about a specific database user (`db` user type), including their roles, status, and type.
- Path Params: user_id, includeLastUsedTime

#### Create a new user
- Method: POST
- Path: /users/db/{user_id}
- Source URL: openapi (Step 6b cross-check fallback)
- Description: Create a new database (`db` user type) user with the specified name. Returns an API key for the newly created user.
- Path Params: user_id, body

#### Delete a user
- Method: DELETE
- Path: /users/db/{user_id}
- Source URL: openapi (Step 6b cross-check fallback)
- Description: Delete a database user. You can't delete your current user.
- Path Params: user_id

#### Activate a user
- Method: POST
- Path: /users/db/{user_id}/activate
- Source URL: openapi (Step 6b cross-check fallback)
- Description: Activate a deactivated database user (`db` user type).
- Path Params: user_id

#### Deactivate a user
- Method: POST
- Path: /users/db/{user_id}/deactivate
- Source URL: openapi (Step 6b cross-check fallback)
- Description: Deactivate a database user (`db` user type).
- Path Params: user_id, body

#### Rotate API key of a user
- Method: POST
- Path: /users/db/{user_id}/rotate-key
- Source URL: openapi (Step 6b cross-check fallback)
- Description: Revoke the current API key for the specified database user (`db` user type) and generate a new one.
- Path Params: user_id

#### Get current user info
- Method: GET
- Path: /users/own-info
- Source URL: openapi (Step 6b cross-check fallback)
- Description: Get information about the currently authenticated user, including username and assigned roles.
- Path Params: none

## Source-derived Index Config Parameters（复用 v1.37.4 + v1.38.0 核对）
## Source-derived Index Config Parameters（weaviate v1.37.4，从 Go 源码机械提取）

> OpenAPI/embedded spec 均不枚举 HNSW index 参数（additionalProperties 透传）——以下为
> entities/vectorindex/hnsw/config.go 的权威定义（json tag 即 API 参数名）：

### dynamicEfMin
```
	DefaultMaxConnections         = 32
	DefaultEFConstruction         = 128
	DefaultEF                     = -1 // indicates "let Weaviate pick"
	DefaultDynamicEFMin           = 100
	DefaultDynamicEFMax           = 500
	DefaultDynamicEFFactor        = 8
	DefaultSkip                   = false
---
	MaxConnections           int               `json:"maxConnections"`
	EFConstruction           int               `json:"efConstruction"`
	EF                       int               `json:"ef"`
	DynamicEFMin             int               `json:"dynamicEfMin"`
	DynamicEFMax             int               `json:"dynamicEfMax"`
	DynamicEFFactor          int               `json:"dynamicEfFactor"`
	VectorCacheMaxObjects    int               `json:"vectorCacheMaxObjects"`
---
	u.EF = DefaultEF
	u.DynamicEFFactor = DefaultDynamicEFFactor
	u.DynamicEFMax = DefaultDynamicEFMax
	u.DynamicEFMin = DefaultDynamicEFMin
	u.Skip = DefaultSkip
	u.FlatSearchCutoff = DefaultFlatSearchCutoff
	u.Distance = vectorIndexCommon.DefaultDistanceMetric
```
关联字段 dynamicEfMax（配对约束候选：Min <= Max）

### flatSearchCutoff
```
	DefaultDynamicEFMax           = 500
	DefaultDynamicEFFactor        = 8
	DefaultSkip                   = false
	DefaultFlatSearchCutoff       = 40000

	FilterStrategySweeping = "sweeping"
	FilterStrategyAcorn    = "acorn"
---
	DynamicEFMax             int               `json:"dynamicEfMax"`
	DynamicEFFactor          int               `json:"dynamicEfFactor"`
	VectorCacheMaxObjects    int               `json:"vectorCacheMaxObjects"`
	FlatSearchCutoff         int               `json:"flatSearchCutoff"`
	Distance                 string            `json:"distance"`
	PQ                       PQConfig          `json:"pq"`
	BQ                       BQConfig          `json:"bq"`
---
	u.DynamicEFMax = DefaultDynamicEFMax
	u.DynamicEFMin = DefaultDynamicEFMin
	u.Skip = DefaultSkip
	u.FlatSearchCutoff = DefaultFlatSearchCutoff
	u.Distance = vectorIndexCommon.DefaultDistanceMetric
	u.PQ = PQConfig{
		Enabled:        DefaultPQEnabled,
```
默认值 40000（int，无范围注解——负值语义待 API 实测）

### replicationDeletionStrategy / replicationFactor（sharding config 面）
replicationFactor 在 embedded spec 4 处 + sharding config；-1 语义待实测。

### v1.38.0 源码参数核对
- Tokenization: 23 文件（如 ['\\entities/deepcopy/models_deepcopy.go', '\\entities/filters/filters_validator_test.go']）

- Distance : 12 文件（如 ['\\entities/additional/classification.go', '\\entities/additional/group.go']）

- ActivityStatus: 2 文件（如 ['\\entities/models/tenant.go', '\\entities/schema/multi_tenancy.go']）

- activityStatus: 1 文件（如 ['\\entities/models/tenant.go']）
