"""Test the image creation workflow."""

from ubuntu_image.flow import State
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
        with patch('ubuntu_image.flow.log.exception') as mock:
            self.assertRaises(RuntimeError, list, state)
        mock.assert_called_once_with('uncaught exception in state machine')
