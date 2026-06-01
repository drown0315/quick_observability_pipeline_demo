import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:todo_app/main.dart';
import 'package:todo_app/workload_run_id.dart';

void main() {
  test('Todo API requests forward the current workload run ID', () async {
    final store = WorkloadRunIdStore()
      ..set('00000000-0000-0000-0000-000000000123');
    late http.Request capturedRequest;
    final repository = HttpTodoRepository(
      client: MockClient((request) async {
        capturedRequest = request;
        return http.Response('[]', 200);
      }),
      workloadRunIdStore: store,
    );

    await repository.listTodos();

    expect(
      capturedRequest.headers['x-workload-run-id'],
      '00000000-0000-0000-0000-000000000123',
    );
  });

  test('Todo API requests omit the workload header before a run ID is set',
      () async {
    late http.Request capturedRequest;
    final repository = HttpTodoRepository(
      client: MockClient((request) async {
        capturedRequest = request;
        return http.Response('[]', 200);
      }),
      workloadRunIdStore: WorkloadRunIdStore(),
    );

    await repository.listTodos();

    expect(capturedRequest.headers, isNot(contains('x-workload-run-id')));
  });
}
