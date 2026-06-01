import 'package:mcp_toolkit/mcp_toolkit.dart';
import 'package:todo_app/workload_run_id.dart' as workload;

/// Return Flutter MCP tool entries for the Todo app debug surface.
///
/// The returned set currently contains one tool, `todo_set_workload_run_id`.
/// It accepts a `run_id` UUID, stores the normalized value in
/// [workloadRunIdStore], and returns the stored value to the caller.
///
/// Args:
///   workloadRunIdStore: Store updated by the MCP tool. When omitted, the app
///       singleton is used so later Todo API requests can send the same
///       workload run ID.
///
/// Returns:
///   A set of MCP entries that can be registered with [MCPToolkitBinding].
///
/// Example:
///   Calling the tool with
///   `{'run_id': '00000000-0000-0000-0000-000000000ABC'}` stores
///   `00000000-0000-0000-0000-000000000abc`.
Set<MCPCallEntry> todoMcpEntries({
  workload.WorkloadRunIdStore? workloadRunIdStore,
}) {
  final store = workloadRunIdStore ?? workload.workloadRunIdStore;
  return {
    MCPCallEntry.tool(
      definition: MCPToolDefinition(
        name: 'todo_set_workload_run_id',
        description: 'Store the workload run UUID for subsequent Todo requests',
        inputSchema: ObjectSchema(
          additionalProperties: false,
          properties: {
            'run_id': Schema.string(description: 'Workload run UUID'),
          },
          required: ['run_id'],
        ),
      ),
      handler: (request) {
        final runId = store.set(request['run_id'] ?? '');
        return MCPCallResult(
          message: 'Stored workload run ID',
          parameters: {'run_id': runId},
        );
      },
    ),
  };
}
