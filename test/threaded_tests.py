# -*- coding: utf-8 -*-
"""
threaded_tests
~~~~~~~~~~~~~~

This file gives access to a threaded test class. Essentially, it provides two
threads and a pipe between them that they can use to communicate. It also
provides events that the two threads can use to coordinate.
"""
import socket
import sys
import threading

try:
    import Queue as queue
except ImportError:
    import queue


class ExplodingThread(threading.Thread):
    """
    A threading subclass that catches exceptions run on it and throws them back
    onto the main thread when joined. Particularly useful for test code where
    it is extremely valuable to have exceptions from the test threads land on
    the main thread.
    """
    def __init__(self, target, args=(), kwargs={}):
        threading.Thread.__init__(self)
        self.target = target
        self.args = args
        self.kwargs = kwargs
        self.__status_queue = queue.Queue()

    def _run(self):
        self.target(*self.args, **self.kwargs)

    def run(self):
        try:
            self._run()
        except BaseException:
            # Catch *all* exceptions.
            self.__status_queue.put(sys.exc_info())
        else:
            self.__status_queue.put(None)

    def join_with_exception(self, timeout=None):
        ex_info = self.__status_queue.get(block=True, timeout=timeout)
        if ex_info is None:
            return
        else:
            raise ex_info[1]


class ThreadedTestCase(object):
    """
    A base class for threaded tests that run two threads until completion.
    """
    def setup_method(self, method):
        self.sock_a, self.sock_b = socket.socketpair()
        self.event_a = threading.Event()
        self.event_b = threading.Event()

    def run_until_complete(self, first_thread, second_thread):
        """
        Executes a pair of functions in two threads, communicating between
        each other. The two functions need to take three arguments: a socket
        and two events. Each function should set the first event after each
        time they've sent data, and should wait on the second event before each
        time they read data.
        """
        thread_a = ExplodingThread(
            target=first_thread,
            args=(self.sock_a, self.event_a, self.event_b),
        )
        thread_b = ExplodingThread(
            target=second_thread,
            args=(self.sock_b, self.event_b, self.event_a),
        )
        thread_a.daemon = True
        thread_b.daemon = True
        thread_a.start()
        thread_b.start()

        # Try to join on the two threads. This weird mess is to ensure that if
        # thread 1 times out because an exception blew up thread 2, we see that
        # exception instead of the timeout. It also ensures that thread 2 can
        # appropriately time out if thread 1 doesn't explode.
        try:
            thread_a.join_with_exception(timeout=2.0)
        except queue.Empty:
            try:
                thread_b.join_with_exception(timeout=2.0)
            except queue.Empty:
                pass
            except Exception:
                raise

            raise
        else:
            thread_b.join_with_exception(timeout=2.0)

        return

    def teardown_method(self, method):
        pass
