#!/usr/bin/env python3

import shutil
import glob
import argparse
import sys
import os
import os.path
import time
import subprocess
import threading

from concurrent.futures import ThreadPoolExecutor

from ilmklib import Graph, makedeps, WorkQueue, TimestampDict

def ts_directory(dirname):
    if os.path.exists(dirname):
        if not os.path.isdir(dirname):
            raise RuntimeException(f"{dirname} exists and is not a directory")
        else:
            return 0

    else:
        return -1

def ts_file(fname):
    if os.path.exists(fname):
        if not os.path.isfile(fname):
            raise RuntimeException(f"{fname} exists and is not a regular file")
        else:
            return os.path.getmtime(fname)

    return -1

def simple_compile(compiler, src, obj, codegen, includedirs, libdirs, libs):

    cmd = [compiler, "-c", "-o", obj, src]

    cmd.extend(codegen)
    cmd.extend([ f"-I{x}" for x in includedirs])
    cmd.extend([ f"-L{x}" for x in libdirs])
    cmd.extend([ f"-l{x}" for x in libs])


    print(cmd)
    subprocess.check_output(cmd)


def do_task(g, compiler, item):

    # If the item was put into the graph with the directory timestamp function,
    # it's a directory.
    item_type = g[item]
    if item_type == "directory":
        print(f"Making directory {item}")
        os.makedirs(item)
    elif item_type == "release_object_file":
        # If the item is an object file, find the .c file in its predecessors and compile it
        # Find the c file
        cf = filter(lambda x: x.endswith(".c"), g.get_direct_predecessors(item))
        x = next(cf)

        simple_compile(compiler, x, item, ["-Ofast"], ["inc"], [], [])
    elif item_type == "debug_object_file":
        # If the item is an object file, find the .c file in its predecessors and compile it
        # Find the c file
        cf = filter(lambda x: x.endswith(".c"), g.get_direct_predecessors(item))
        x = next(cf)

        simple_compile(compiler, x, item, ["-Og", "-ggdb3"], ["inc"], [], [])
    elif item_type == "release_main_output":
        # Otherwise its the final output. Find all the object files that go
        # into it and compile it.
        of = filter(lambda x: x.endswith(".o"), g.get_direct_predecessors(item))
        final_cmd = [compiler] + list(of) + ["-o", item]
        print(final_cmd)
        subprocess.check_output(final_cmd)
    elif item_type == "debug_main_output":
        # Otherwise its the final output. Find all the object files that go
        # into it and compile it.
        of = filter(lambda x: x.endswith(".o"), g.get_direct_predecessors(item))
        final_cmd = [compiler] + list(of) + ["-o", item, "-Og", "-ggdb3"]
        print(final_cmd)
        subprocess.check_output(final_cmd)
    else:
        print(f"Unexpected item type for {item}")


def tw(w, g, tsd):

    cc = tsd["cc"]
    while True:

        try:
            item = w.get_item(True)
        except Exception as e:
            item = None
            print(e)
            w.mark_error()

        if not item:
            break

        try:
            do_task(g, cc, item)
            w.mark_done(item)
        except Exception as e:
            print(e)
            w.mark_error()
            return

def do_main():

    # Do argument parsing
    parse = argparse.ArgumentParser(add_help=False)
    parse.add_argument('-v', '--verbose', action='count', default=0)
    parse.add_argument('-m', '--multitask', action='store_true')
    parse.add_argument('-j', '--jobs', type=int, default=1)
    parse.add_argument('-t', '--targets', nargs='*')
    #parse.add_argument('targets', nargs='*')
    args = parse.parse_args(sys.argv[1:])
    if args.multitask:
        ncpus = os.cpu_count()
    else:
        ncpus = args.jobs

    tsd = TimestampDict()
    tsd.loadkeydir(".env_vars")

    # Default cc to gcc
    if not "cc" in tsd:
        tsd["cc"] = "gcc"

    targets = args.targets if args.targets else []
    for target in targets:
        if target == "clean":
            try:
                shutil.rmtree("out")
            except:
                pass
            return
        pass

    # Create the graph, add the output directory(ies)
    g = Graph()

    # Find all the headers and c source files
    cfiles = glob.glob("**/*.c")
    hfiles = glob.glob("**/*.h")
    for f in hfiles:
        # Add all the headers to the graph
        g.add_vertex(f, "file")

    g.add_vertex(tsd.name("cc"), "tsd_entry")

    mkdeps = []
    # Run makedeps on each of the source files with the inc dir
    with ThreadPoolExecutor() as executor:
        mkdeps = executor.map(lambda x:(x, *makedeps(x, "inc", False, tsd["cc"])), cfiles)

    mkdeps = list(mkdeps)

    finales = []
    variants = ["release"]
    if "debug" in targets:
        variants = ["debug"]
    if "all" in targets:
        variants = ["debug", "release"]

    for v in variants:
        ov = os.path.join("out", v)
        g.add_vertex(ov, "directory")

        # Add the final binary name
        finale = os.path.join(ov, "collect")
        finales.append(finale)
        g.add_vertex(finale, v + "_main_output")

        g.add_edge(finale, tsd.name("cc"))
        for f, o, deps in mkdeps:
            # Add all the c source files to the graph
            if f not in g:
                g.add_vertex(f, "file")
            # Run makedeps on each of the source files with the inc dir
            #o, deps = cc.makedeps(f, "inc")

            # Add the object file to the graph
            ofile = os.path.join(ov, o)
            g.add_vertex(ofile, v + "_object_file")

            # Add edges from `out/` to the object file
            g.add_edge(ofile, ov)
            # Headers + c file to object file
            g.add_edges(ofile, deps)

            g.add_edge(ofile, tsd.name("cc"))
            # object file to final output
            g.add_edge(finale, ofile)

        pass


    ts_tsd_entry = lambda x : tsd.time(x)
    func_dict = {
        "file" : ts_file,
        "directory" : ts_directory,
        "release_main_output" : ts_file,
        "debug_main_output" : ts_file,
        "release_object_file" : ts_file,
        "debug_object_file" : ts_file,
        "tsd_entry" :  ts_tsd_entry,
    }

    # Create a work queue with the end goal of the finale file
    w = WorkQueue(g, func_dict)
    for f in finales:
        w.activate(f)

    if "print" in targets:
        for item in w.get_updated():
            print(item)
        sys.exit(0)

    threads = []
    nthreads = ncpus

    # Create and start some threads
    for i in range(nthreads):
        t = threading.Thread(target=tw, args=(w, g, tsd))
        threads.append(t)
        t.start()

    # Wait for all the threads to complete
    for t in threads:
        t.join()

    # If there was some error, exit with a nonzero code
    if w.error:
        sys.exit(1)


if __name__ == "__main__":
    do_main()
