////////////////////////////////////////////////////////////////////////////////
// Author: Peter Elmers (peter.elmers@rice.edu)
////////////////////////////////////////////////////////////////////////////////

/* Very simple example for demand-driven execution:
 * Prescribe 2n steps, but only demand n items.
 */

[ int X: i ];

( $initialize: () ) -> ( S: $range(0, 10) ), [ X: 0 ];

( S: i )
    <- [ X: i / 2 ]
    -> [ X: i + 1 ];

( $finalize: () ) <- [ X: 5 ];

