import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:todo_app/main.dart';

void main() {
  testWidgets('user can create, complete, and delete a Todo', (tester) async {
    final repository = MemoryTodoRepository();
    await tester.pumpWidget(TodoApp(repository: repository));
    await tester.pumpAndSettle();

    await tester.enterText(find.byKey(const Key('new-todo-title')), 'buy milk');
    await tester.tap(find.byKey(const Key('add-todo')));
    await tester.pumpAndSettle();

    expect(find.text('buy milk'), findsOneWidget);
    expect(find.bySemanticsLabel('Complete buy milk'), findsOneWidget);
    expect(find.bySemanticsLabel('Delete buy milk'), findsOneWidget);

    await tester.tap(find.byType(Checkbox));
    await tester.pumpAndSettle();

    expect(repository.todos.single.completed, isTrue);

    await tester.tap(find.byIcon(Icons.delete));
    await tester.pumpAndSettle();

    expect(find.text('buy milk'), findsNothing);
    expect(repository.todos, isEmpty);
  });

  testWidgets('user can manually trigger a temporary client exception', (
    tester,
  ) async {
    await tester.pumpWidget(TodoApp(repository: MemoryTodoRepository()));
    await tester.pumpAndSettle();

    await tester.tap(find.byKey(const Key('trigger-client-exception')));

    expect(tester.takeException(), isA<StateError>());
  });

  testWidgets('completing a mobile-crash Todo raises an uncaught exception', (
    tester,
  ) async {
    await tester.pumpWidget(TodoApp(repository: MemoryTodoRepository()));
    await tester.pumpAndSettle();
    await tester.enterText(
      find.byKey(const Key('new-todo-title')),
      'mobile-crash-demo',
    );
    await tester.tap(find.byKey(const Key('add-todo')));
    await tester.pumpAndSettle();

    await tester.tap(find.byType(Checkbox));

    expect(tester.takeException(), isA<StateError>());
  });
}

class MemoryTodoRepository implements TodoRepository {
  final List<Todo> todos = [];
  int _nextId = 1;

  @override
  Future<List<Todo>> listTodos() async => List.of(todos);

  @override
  Future<Todo> createTodo(String title) async {
    final todo = Todo(id: _nextId++, title: title, completed: false);
    todos.add(todo);
    return todo;
  }

  @override
  Future<Todo> setCompleted(int id, bool completed) async {
    final index = todos.indexWhere((todo) => todo.id == id);
    final current = todos[index];
    final updated = Todo(id: id, title: current.title, completed: completed);
    todos[index] = updated;
    return updated;
  }

  @override
  Future<void> deleteTodo(int id) async {
    todos.removeWhere((todo) => todo.id == id);
  }
}
