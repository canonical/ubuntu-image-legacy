"""Flow for building a disk image."""

from collections import deque
from logging import getLogger


log = getLogger('ubuntu-image')


class State:
    def __init__(self):
        # Variables which manage state transitions.
        self._next = deque()
        self._debug_step = 1

    def __iter__(self):
        return self

    def _pop(self):
        step = self._next.popleft()
        # step could be a partial or a method.
        name = getattr(step, 'func', step).__name__
        log.debug('-> [{:2}] {}'.format(self._debug_step, name))
        return step, name

    def __next__(self):
        try:
            step, name = self._pop()
            step()
            self._debug_step += 1
        except IndexError:
            # Do not chain the exception.
            raise StopIteration from None
        except:
            log.exception('uncaught exception in state machine')
            raise

    def run_thru(self, stop_after):
        """Total hack to partially run the state machine.

        :param stop_after: Name of method to run the state machine
            through.  In other words, the state machine runs until the
            named method completes.
        """
        while True:
            try:
                step, name = self._pop()
            except (StopIteration, IndexError):
                # We're done.
                break
            step()
            self._debug_step += 1
            if name == stop_after:
                break

    def run_until(self, stop_before):
        """Total hack to partially run the state machine.

        :param stop_before: Name of method that the state machine is run
            until the method is reached.  Unlike `run_thru()` the named
            method is not run.
        """
        while True:
            try:
                step, name = self._pop()
            except (StopIteration, IndexError):
                # We're done.
                break
            if name == stop_before:
                # Stop executing, but not before we push the last state back
                # onto the deque.  Otherwise, resuming the state machine would
                # skip this step.
                self._next.appendleft(step)
                break
            step()
            self._debug_step += 1
