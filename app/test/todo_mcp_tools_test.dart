import 'package:flutter_test/flutter_test.dart';
import 'package:todo_app/todo_mcp_tools.dart';
import 'package:todo_app/workload_run_id.dart';

void main() {
  test('todo workload MCP tool stores a validated run ID', () async {
    final store = WorkloadRunIdStore();
    final entry = todoMcpEntries(workloadRunIdStore: store).single;

    expect(entry.key, 'todo_set_workload_run_id');
    expect(entry.value.toolDefinition?['inputSchema'], {
      'type': 'object',
      'additionalProperties': false,
      'properties': {
        'run_id': {'type': 'string', 'description': 'Workload run UUID'},
      },
      'required': ['run_id'],
    });

    final result = await entry.value.handler({
      'run_id': '00000000-0000-0000-0000-000000000ABC',
    });

    expect(result['run_id'], '00000000-0000-0000-0000-000000000abc');
    expect(store.current, '00000000-0000-0000-0000-000000000abc');
  });

  test('todo workload MCP tool rejects invalid run IDs', () async {
    final store = WorkloadRunIdStore()
      ..set('00000000-0000-0000-0000-000000000123');
    final entry = todoMcpEntries(workloadRunIdStore: store).single;

    expect(
      () => entry.value.handler({'run_id': 'not-a-uuid'}),
      throwsFormatException,
    );
    expect(store.current, '00000000-0000-0000-0000-000000000123');
  });
}
