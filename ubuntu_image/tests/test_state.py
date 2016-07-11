"""Test the image creation workflow."""

from contextlib import suppress
from ubuntu_image.state import State
from unittest import TestCase
from unittest.mock import patch


class MyState(State):
    def __init__(self):
        super().__init__()
        self.accumulator = []
        self._next.append(self.first)

    def first(self):
        self.accumulator.append(1)
        self._next.append(self.second)

    def second(self):
        self.accumulator.append(2)
        self._next.append(self.third)

    def third(self):
        self.accumulator.append(3)


class MyBrokenState(State):
    def __init__(self):
        super().__init__()
        self.accumulator = []
        self._next.append(self.first)

    def first(self):
        self.accumulator.append(1)
        self._next.append(self.second)

    def second(self):
        raise RuntimeError


class TestState(TestCase):
    """Test basic state transitions."""

    def test_run_thru(self):
        state = MyState()
        state.run_thru('second')
        self.assertEqual(state.accumulator, [1, 2])

    def test_run_until(self):
        state = MyState()
        state.run_until('second')
        self.assertEqual(state.accumulator, [1])

    def test_run_to_completion(self):
        state = MyState()
        list(state)
        self.assertEqual(state.accumulator, [1, 2, 3])

    def test_exception_in_step(self):
        state = MyBrokenState()
        with patch('ubuntu_image.state.log.exception') as mock:
            self.assertRaises(RuntimeError, list, state)
        mock.assert_called_once_with('uncaught exception in state machine')

    def test_context_manager(self):
        with MyState() as state:
            list(state)
        self.assertEqual(state.accumulator, [1, 2, 3])

    def test_run_thru_past_the_end(self):
        # Running through a nonexistent state just runs through to the end of
        # the state machine.
        with MyState() as state:
            state.run_thru('not-a-state')
        self.assertEqual(state.accumulator, [1, 2, 3])

    def test_run_thru_exception_closes_resources(self):
        with MyBrokenState() as state:
            state.resources.callback(setattr, state, 'x', 5)
            with suppress(RuntimeError):
                state.run_thru('not-a-state')
        self.assertEqual(state.x, 5)

    def test_run_until_past_the_end(self):
        # Running until a nonexistent state just runs through to the end of
        # the state machine.
        with MyState() as state:
            state.run_until('not-a-state')
        self.assertEqual(state.accumulator, [1, 2, 3])

    def test_run_until_exception_closes_resources(self):
        with MyBrokenState() as state:
            state.resources.callback(setattr, state, 'x', 5)
            with suppress(RuntimeError):
                state.run_until('not-a-state')
        self.assertEqual(state.x, 5)
