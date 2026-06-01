import 'package:mcp_toolkit/mcp_toolkit.dart';
import 'package:todo_app/workload_run_id.dart' as workload;

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
