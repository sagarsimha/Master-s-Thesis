# Master-s-Thesis
Conditional Independence Test for Categorical Data towards Causal Discovery and Application in Bibliometrics

Abstract :
This work describes the design and evaluation of a conditional independence
test for categorical data towards causal discovery. Conditional independence
(CI) testing is at the crux of a causal discovery framework. Constraint-based
causal discovery algorithm suite such as PC (Spirtes et al. [2000]), PCMCI
(Runge et al. [2019]), PCMCIplus (Runge [2020b]) and LPCMCI (Gerhardus
and Runge [2020]), all use CI tests to infer causal relations from purely ob-
servational data. The theoretical performance of these algorithms is usually
measured by assuming an ’oracle’ CI which readily has the knowledge of de-
pendence or independence. However, in practice this is not available and the
performance of the causal discovery algorithm heavily depends on the perfor-
mance of the CI test under different distributions of the data. Therefore the
design of a calibrated CI test is paramount. Here, particular focus is on the
case of categorical data and a test is presented based on conditional mutual in-
formation (CMI) combined with a local permutation scheme - CMISymbPerm.
The test is formulated as a hypothesis test of independence - X Y | Z
while any or all of the variables may be multivariate. The test is evaluated
using a Bayesian Network with link strength as a data generating process and
numerical experiments are run over different parameter configurations from
50 upto 2000 samples, number of symbols upto 6 and dimensions of Z up
to 4. The experiments demonstrates that the test reliably approximates the
true null distribution. Numerical experiments also include the comparison of
CMISymbPerm with G 2 test statistic which approximates the null as a χ 2 dis-
tribution. Results show that CMISymbPerm and G 2 converge in type I error
for large samples. The permutation scheme grows O(c n ) in time complexity
with number of samples as compared to G 2 O(1). CMISymbPerm should be
preferred for lower sample sizes, larger dimensions and higher number of sym-
bols, while G 2 should be preferred for larger sample sizes or when time is a
constraint. The PC algorithm with partial correlation test is then applied on
Open Academic Graph 2.1 (OAG [2020]) to investigate causal links in Biblio-
metrics data of continuous variables.
The work on categorical CI testing is heavily based on CMIknn (Runge
[2018]), a non-parametric test for continuous data. All the methods imple-
mented are contributed as part of the package TIGRAMITE (https://github.com/jakobrunge/tigramite)
