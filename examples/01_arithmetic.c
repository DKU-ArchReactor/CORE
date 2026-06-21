#include "common.h"

int main(void) {
    print_string("01 arithmetic\n");

    int a = 30;
    int b = 7;
    int sum = a + b;
    int diff = a - b;
    int product = a * b;
    int quotient = product / b;
    int remainder = product % 11;

    print_result(sum == 37 && diff == 23 && product == 210 && quotient == 30 && remainder == 1);
    program_exit();
    return 0;
}
