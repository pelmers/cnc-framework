#include "SimpleDemand.h"


void SimpleDemand_cncInitialize(SimpleDemandArgs *args, SimpleDemandCtx *ctx) {


    { // Prescribe "S" steps
        s64 _i;
        for (_i = 0; _i < 10; _i++) {
            cncPrescribe_S(_i, ctx);
        }
    }

    // Put "X" items
    int *X = cncItemAlloc(sizeof(*X));
    /* TODO: Initialize X */
    *X = -1;
    cncPut_X(X, 0, ctx);

    // Set finalizer function's tag
    SimpleDemand_await(ctx);

}


void SimpleDemand_cncFinalize(int X, SimpleDemandCtx *ctx) {

    /* TODO: Do something with X */
    printf("final answer is %d, expected 9.\n", X);

}


