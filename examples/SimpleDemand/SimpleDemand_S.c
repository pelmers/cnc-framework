#include "SimpleDemand.h"

/**
 * Step function definition for "S"
 */
void SimpleDemand_S(cncTag_t i, int X0, int d, SimpleDemandCtx *ctx) {

    //
    // OUTPUTS
    //

    // Put "X1" items
    int *X1 = cncItemAlloc(sizeof(*X1));
    /* TODO: Initialize X1 */
    *X1 = 2*X0;
    printf("just put %d as %d\n", i, *X1);
    cncPut_X(X1, i + 1, ctx);

}
