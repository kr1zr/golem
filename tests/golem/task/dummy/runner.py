"""Test script for running a single instance of a dummy task.
The task simply computes hashes of some random data and requires
no external tools. The amount of data processed (ie hashed) and computational
difficulty is configurable, see comments in DummyTaskParameters.
"""

from task import DummyTask, DummyTaskParameters
from golem.client import start_client
from golem.environments.environment import Environment
from golem.network.transport.tcpnetwork import TCPAddress

import os
import re
import subprocess
import sys
from threading import Thread
import time
from twisted.internet import reactor


REQUESTING_NODE_KIND = "requester"
COMPUTING_NODE_KIND = "computer"


def run_requesting_node(num_subtasks = 3):

    def report(msg):
        print "[REQUESTING NODE {}] {}".format(os.getpid(), msg)

    start_time = time.time()
    report("Starting...")
    client = start_client()
    report("Started in {:.1f} s".format(time.time() - start_time))

    params = DummyTaskParameters(1024, 2048, 256, 0x0001ffff)
    task = DummyTask(client.get_node_name(), params, num_subtasks)
    client.enqueue_new_task(task)

    port = client.p2pservice.cur_port
    requester_addr = "{}:{}".format(client.node.prv_addr, port)
    report("Listening on: {}".format(requester_addr))

    def report_status():
        finished = False
        while True:
            time.sleep(5)
            report("Ping!")
            if not finished and task.finished_computation():
                report("Task finished")
                finished = True

    reactor.callInThread(report_status)
    reactor.run()


def run_computing_node(peer_address, fail_after = None):

    def report(msg):
        print "[COMPUTING NODE {}] {}".format(os.getpid(), msg)

    start_time = time.time()
    report("Starting...")
    client = start_client()
    report("Started in {:.1f} s".format(time.time() - start_time))

    class DummyEnvironment(Environment):
        @classmethod
        def get_id(cls):
            return "DUMMY"

    dummy_env = DummyEnvironment()
    dummy_env.accept_tasks = True
    client.environments_manager.add_environment(dummy_env)

    report("Connecting to requester node at {}:{} ..."
           .format(peer_address.address, peer_address.port))
    client.connect(peer_address)

    def report_status(fail_after = None):
        t0 = time.time()
        n = 0
        while True:
            if fail_after and time.time() - t0 > fail_after:
                report("Failure!")
                reactor.callFromThread(reactor.stop)
                time.sleep(5)
                return
            n += 1
            if n % 5 == 0:
                report("Ping!")
            time.sleep(1)

    reactor.callInThread(report_status, fail_after)
    reactor.run()
    sys.exit(1)


# Global var set by a thread monitoring the status of the requester node
task_finished = False


def run_simulation(num_computing_nodes = 2, num_subtasks = 3, timeout = 120,
                   node_failure_times = None):

    # We need to pass the PYTHONPATH to the child processes
    pythonpath = "".join(dir + os.pathsep for dir in sys.path)
    env = os.environ.copy()
    env["PYTHONPATH"] = pythonpath

    start_time = time.time()

    # Start the requesting node in a separate process
    requesting_proc = subprocess.Popen(
        ["python", "-u", __file__, REQUESTING_NODE_KIND, str(num_subtasks)],
        bufsize = 1,  # line buffered
        env = env,
        stdout = subprocess.PIPE)

    # Scan the requesting node's stdout for the address
    address_re = re.compile("\[REQUESTING NODE [0-9]+\] Listening on: (.+)")
    while True:
        line = requesting_proc.stdout.readline().strip()
        print line
        m = address_re.match(line)
        if m:
            requester_address = m.group(1)
            break

    # Start computing nodes in a separate processes
    computing_procs = []
    for n in range(0, num_computing_nodes):
        cmdline = [
            "python", "-u", __file__, COMPUTING_NODE_KIND, requester_address]
        if node_failure_times and len(node_failure_times) > n:
            # Simulate failure of a computing node
            cmdline.append(str(node_failure_times[n]))
        proc = subprocess.Popen(
            cmdline,
            bufsize = 1,
            env = env,
            stdout = subprocess.PIPE)
        computing_procs.append(proc)

    all_procs = computing_procs + [requesting_proc]
    task_finished_status = "[REQUESTING NODE {}] Task finished".format(
        requesting_proc.pid)

    global task_finished
    task_finished = False

    def monitor_subprocess(proc):
        global task_finished
        while not proc.returncode:
            line = proc.stdout.readline().strip()
            if line:
                print line
            if line == task_finished_status:
                task_finished = True

    monitor_threads = [Thread(target = monitor_subprocess,
                              name = "monitor {}".format(proc.pid),
                              args=(proc,))
                       for proc in all_procs]

    for th in monitor_threads:
        th.setDaemon(True)
        th.start()

    # Wait until timeout elapses or the task is computed
    try:
        while not task_finished:
            if time.time() - start_time > timeout:
                return "Computation timed out"
            # Check if all subprocesses are alive
            for proc in all_procs:
                proc.poll()
                if proc.returncode:
                    return "Node exited with return code {}".format(
                        proc.returncode)
            time.sleep(1.0)
        return None
    finally:
        print "Stopping nodes..."

        for proc in all_procs:
            proc.poll()
            if not proc.returncode:
                proc.kill()


if __name__ == "__main__":
    if len(sys.argv) == 3 and sys.argv[1] == REQUESTING_NODE_KIND:
        # I'm a requesting node, second arg is the number of subtasks
        run_requesting_node(int(sys.argv[2]))
    elif len(sys.argv) in [3,4] and sys.argv[1] == COMPUTING_NODE_KIND:
        # I'm a computing node, second arg is the address to connect to
        fail_after = float(sys.argv[3]) if len(sys.argv) == 4 else None
        run_computing_node(TCPAddress.parse(sys.argv[2]), fail_after=fail_after)
    elif len(sys.argv) == 1:
        # I'm the main script, run simulation
        error_msg = run_simulation(
            num_computing_nodes = 2, num_subtasks = 4, timeout = 120)
        if error_msg:
            print "Dummy task computation failed:", error_msg
            sys.exit(1)
