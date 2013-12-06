# Usage:
# cat cod_*.log | awk -f plot_perf_log.awk > cod.plot
# xplot.org cod.plot

BEGIN {
    print "timeval double";
}

{
    start = $1;
    end = $2;
    duration = end - start;
    event = $3;
    shape = "plus";
    color = -1;
}

event == "data" {
    color = 2; # red
}

event == "write" {
    color = 1; # green
}

event == "read" {
    color = 3; # blue
    # TODO: amount of data in buffer
}

event == "packet" {
    color = 4; # yellow
}

event == "playing" {
    color = 5; # purple
}

color >= 0 {
    print shape, start, duration, color;
    print shape, end, duration, color;
    print "line", start, duration, end, duration, color;
}


    
    
    