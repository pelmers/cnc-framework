#include "SimpleDemand.h"

int cncMain(int argc, char *argv[]) {

    // Create a new graph context
    SimpleDemandCtx *context = SimpleDemand_create();

    // TODO: Set up arguments for new graph initialization
    // Note that you should define the members of
    // this struct by editing SimpleDemand_defs.h.
    SimpleDemandArgs *args = NULL;


    // Launch the graph for execution
    SimpleDemand_launch(args, context);

    // Exit when the graph execution completes
    CNC_SHUTDOWN_ON_FINISH(context);

    return 0;
}
