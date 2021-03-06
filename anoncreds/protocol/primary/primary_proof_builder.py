from typing import Sequence

from anoncreds.protocol.globals import LARGE_VPRIME, LARGE_MVECT, LARGE_E_START, \
    LARGE_ETILDE, \
    LARGE_VTILDE, LARGE_UTILDE, LARGE_RTILDE, LARGE_ALPHATILDE, ITERATIONS, \
    DELTA
from anoncreds.protocol.primary.primary_proof_common import calcTge, calcTeq
from anoncreds.protocol.types import PrimaryClaim, Predicate, PrimaryInitProof, \
    PrimaryEqualInitProof, PrimaryPrecicateGEInitProof, PrimaryProof, \
    PrimaryEqualProof, PrimaryPredicateGEProof, \
    ID, ClaimInitDataType
from anoncreds.protocol.utils import getUnrevealedAttrs, fourSquares
from anoncreds.protocol.wallet.prover_wallet import ProverWallet
from config.config import cmod


class PrimaryClaimInitializer:
    def __init__(self, wallet: ProverWallet):
        self._wallet = wallet

    async def genClaimInitData(self, schemaId: ID) -> ClaimInitDataType:
        pk = await self._wallet.getPublicKey(schemaId)
        ms = await self._wallet.getMasterSecret(schemaId)
        vprime = cmod.randomBits(LARGE_VPRIME)
        N = pk.N
        Rms = pk.Rms
        S = pk.S
        U = (S ** vprime) * (Rms ** ms) % N

        return ClaimInitDataType(U=U, vPrime=vprime)

    async def preparePrimaryClaim(self, schemaId: ID, claim: PrimaryClaim):
        claimInitDat = await self._wallet.getPrimaryClaimInitData(schemaId)
        newV = claim.v + claimInitDat.vPrime
        claim = claim._replace(v=newV)
        return claim


class PrimaryProofBuilder:
    def __init__(self, wallet: ProverWallet):
        self._wallet = wallet

    async def initProof(self, schemaKey, c1: PrimaryClaim,
                        revealedAttrs: Sequence[str],
                        predicates: Sequence[Predicate],
                        m1Tilde, m2Tilde) -> PrimaryInitProof:
        if not c1:
            return None

        eqProof = await self._initEqProof(schemaKey, c1, revealedAttrs,
                                          m1Tilde, m2Tilde)
        geProofs = []
        for predicate in predicates:
            geProof = await self._initGeProof(schemaKey, eqProof, c1,
                                              predicate)
            geProofs.append(geProof)
        return PrimaryInitProof(eqProof, geProofs)

    async def finalizeProof(self, schemaKey, cH,
                            initProof: PrimaryInitProof) -> PrimaryProof:
        if not initProof:
            return None

        cH = cmod.integer(cH)
        eqProof = await self._finalizeEqProof(schemaKey, cH,
                                              initProof.eqProof)
        geProofs = []
        for initGeProof in initProof.geProofs:
            geProof = await self._finalizeGeProof(schemaKey, cH, initGeProof,
                                                  eqProof)
            geProofs.append(geProof)
        return PrimaryProof(eqProof, geProofs)

    async def _initEqProof(self, schemaKey, c1: PrimaryClaim,
                           revealedAttrs: Sequence[str], m1Tilde, m2Tilde) \
            -> PrimaryEqualInitProof:
        m2Tilde = m2Tilde if m2Tilde else cmod.integer(
            cmod.randomBits(LARGE_MVECT))
        unrevealedAttrs = getUnrevealedAttrs(c1.encodedAttrs, revealedAttrs)
        mtilde = self._getMTilde(unrevealedAttrs)

        Ra = cmod.integer(cmod.randomBits(LARGE_VPRIME))
        pk = await self._wallet.getPublicKey(ID(schemaKey))

        A, e, v = c1.A, c1.e, c1.v
        Aprime = A * (pk.S ** Ra) % pk.N
        vprime = (v - e * Ra)
        eprime = e - (2 ** LARGE_E_START)

        etilde = cmod.integer(cmod.randomBits(LARGE_ETILDE))
        vtilde = cmod.integer(cmod.randomBits(LARGE_VTILDE))

        Rur = 1 % pk.N
        for k, value in unrevealedAttrs.items():
            if k in c1.encodedAttrs:
                Rur = Rur * (pk.R[k] ** mtilde[k])
        Rur *= pk.Rms ** m1Tilde
        Rur *= pk.Rctxt ** m2Tilde

        # T = ((Aprime ** etilde) * Rur * (pk.S ** vtilde)) % pk.N
        T = calcTeq(pk, Aprime, etilde, vtilde, mtilde, m1Tilde, m2Tilde,
                    unrevealedAttrs.keys())

        return PrimaryEqualInitProof(c1, Aprime, T, etilde, eprime, vtilde,
                                     vprime, mtilde, m1Tilde, m2Tilde,
                                     unrevealedAttrs.keys(), revealedAttrs)

    async def _initGeProof(self, schemaKey, eqProof: PrimaryEqualInitProof,
                           c1: PrimaryClaim, predicate: Predicate) \
            -> PrimaryPrecicateGEInitProof:
        # gen U for Delta
        pk = await self._wallet.getPublicKey(ID(schemaKey))
        k, value = predicate.attrName, predicate.value
        delta = c1.encodedAttrs[k] - value
        if delta < 0:
            raise ValueError("Predicate is not satisfied")

        u = fourSquares(delta)

        # prepare C list
        r = {}
        T = {}
        CList = []
        for i in range(0, ITERATIONS):
            r[str(i)] = cmod.integer(cmod.randomBits(LARGE_VPRIME))
            T[str(i)] = (pk.Z ** u[str(i)]) * (pk.S ** r[str(i)]) % pk.N
            CList.append(T[str(i)])
        r[DELTA] = cmod.integer(cmod.randomBits(LARGE_VPRIME))
        T[DELTA] = (pk.Z ** delta) * (pk.S ** r[DELTA]) % pk.N
        CList.append(T[DELTA])

        # prepare Tau List
        utilde = {}
        rtilde = {}
        for i in range(0, ITERATIONS):
            utilde[str(i)] = cmod.integer(cmod.randomBits(LARGE_UTILDE))
            rtilde[str(i)] = cmod.integer(cmod.randomBits(LARGE_RTILDE))
        rtilde[DELTA] = cmod.integer(cmod.randomBits(LARGE_RTILDE))
        alphatilde = cmod.integer(cmod.randomBits(LARGE_ALPHATILDE))

        TauList = calcTge(pk, utilde, rtilde, eqProof.mTilde[k], alphatilde, T)
        return PrimaryPrecicateGEInitProof(CList, TauList, u, utilde, r, rtilde,
                                           alphatilde, predicate, T)

    async def _finalizeEqProof(self, schemaKey, cH,
                               initProof: PrimaryEqualInitProof) -> PrimaryEqualProof:
        e = initProof.eTilde + (cH * initProof.ePrime)
        v = initProof.vTilde + (cH * initProof.vPrime)

        m = {}
        for k in initProof.unrevealedAttrs:
            m[str(k)] = initProof.mTilde[str(k)] + (
                cH * initProof.c1.encodedAttrs[str(k)])
        ms = await self._wallet.getMasterSecret(ID(schemaKey))
        m1 = initProof.m1Tilde + (cH * ms)
        m2 = initProof.m2Tilde + (cH * initProof.c1.m2)

        return PrimaryEqualProof(e, v, m, m1, m2, initProof.Aprime,
                                 initProof.revealedAttrs)

    async def _finalizeGeProof(self, schemaKey, cH,
                               initProof: PrimaryPrecicateGEInitProof,
                               eqProof: PrimaryEqualProof) \
            -> PrimaryPredicateGEProof:
        u = {}
        r = {}
        urproduct = 0
        for i in range(0, ITERATIONS):
            u[str(i)] = initProof.uTilde[str(i)] + cH * initProof.u[str(i)]
            r[str(i)] = initProof.rTilde[str(i)] + cH * initProof.r[str(i)]
            urproduct += initProof.u[str(i)] * initProof.r[str(i)]
            r[DELTA] = initProof.rTilde[DELTA] + cH * initProof.r[DELTA]

        alpha = initProof.alphaTilde + cH * (initProof.r[DELTA] - urproduct)

        k, value = initProof.predicate.attrName, initProof.predicate.value
        return PrimaryPredicateGEProof(u, r, alpha, eqProof.m[str(k)],
                                       initProof.T, initProof.predicate)

    def _getMTilde(self, unrevealedAttrs):
        mtilde = {}
        for key, value in unrevealedAttrs.items():
            mtilde[key] = cmod.integer(cmod.randomBits(LARGE_MVECT))
        return mtilde
