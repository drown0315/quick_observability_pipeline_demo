import 'package:flutter_test/flutter_test.dart';
import 'package:todo_app/workload_run_id.dart';

void main() {
  test('workload run ID store accepts UUIDs and rejects invalid values', () {
    final store = WorkloadRunIdStore();

    expect(
      store.set('00000000-0000-0000-0000-000000000ABC'),
      '00000000-0000-0000-0000-000000000abc',
    );
    expect(store.current, '00000000-0000-0000-0000-000000000abc');

    expect(() => store.set('not-a-uuid'), throwsFormatException);
    expect(store.current, '00000000-0000-0000-0000-000000000abc');
  });
}
