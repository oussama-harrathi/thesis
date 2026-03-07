"""
Unit tests for app.utils.chunk_classifier

All functions under test are pure (no I/O, no DB), so tests run fast and
deterministically.  The test cases cover each rule group and the priority
order (admin > refs > exercise > instructional).
"""

from __future__ import annotations

import pytest

from app.utils.chunk_classifier import ChunkType, classify_chunk_type


# ── Helpers ───────────────────────────────────────────────────────────────────


def _classify(text: str) -> ChunkType:
    ct, _score, _rules = classify_chunk_type(text)
    return ct


# ── ADMIN_ASSESSMENT ─────────────────────────────────────────────────────────


class TestAdminAssessment:
    def test_explicit_internal_assessment(self):
        text = (
            "Internal Assessment — Mathematics HL\n"
            "The internal assessment is worth 20% of the final grade.\n"
            "It consists of a mathematical exploration submitted in Paper 2.\n"
            "Duration: 90 minutes.  The paper is compulsory for all candidates."
        )
        assert _classify(text) == ChunkType.admin_assessment

    def test_mark_allocation(self):
        text = (
            "Section A is worth 40 marks.\n"
            "Section B is worth 60 marks.\n"
            "Total marks: 100.  Mark allocation:\n"
            "  Q1: 15 marks,  Q2: 25 marks, remainder from Paper 1."
        )
        assert _classify(text) == ChunkType.admin_assessment

    def test_paper_structure_and_duration(self):
        text = (
            "Paper 1 – No calculator allowed.  Duration: 1h 30 min.\n"
            "Paper 2 – GDC required.  Compulsory questions.\n"
            "Grade boundary: 70% for a grade 6."
        )
        assert _classify(text) == ChunkType.admin_assessment

    def test_markscheme_text(self):
        text = (
            "Mark scheme for Section A:\n"
            "Q1. Award 2 marks for correct expansion.\n"
            "Q2. Award 1 mark for each correct root.  Total marks: 4."
        )
        assert _classify(text) == ChunkType.admin_assessment

    def test_ib_diploma_context(self):
        text = (
            "IB Diploma Programme — Mathematics Applications and Interpretation SL\n"
            "External assessment comprises Paper 1 and Paper 2.\n"
            "Assessment criteria are published by the IB."
        )
        assert _classify(text) == ChunkType.admin_assessment

    def test_weak_admin_signal_stays_instructional(self):
        """A single 'duration' mention in instructional text must NOT trigger admin."""
        text = (
            "This chapter covers the Euclidean algorithm.  The running duration "
            "of the algorithm depends on the size of the inputs."
        )
        # 'duration' appears once (+2) — below _ADMIN_THRESHOLD of 5
        result = _classify(text)
        assert result != ChunkType.admin_assessment


# ── REFERENCES_BOILERPLATE ────────────────────────────────────────────────────


class TestReferencesBoilerplate:
    def test_references_heading_alone(self):
        text = "References\n\n[1] Knuth, D.E. (1968). The Art of Computer Programming.\n"
        assert _classify(text) == ChunkType.references_boilerplate

    def test_bibliography_heading(self):
        text = "\nBibliography\n\n[1] Aho, A. V., & Ullman, J. D. (1972)...\n"
        assert _classify(text) == ChunkType.references_boilerplate

    def test_glossary_heading(self):
        text = "Glossary\n\nAlgorithm: a finite sequence of instructions.\n"
        assert _classify(text) == ChunkType.references_boilerplate

    def test_mcs_page_header_artifact(self):
        text = "MCS — Discrete Mathematics — Page 47"
        assert _classify(text) == ChunkType.references_boilerplate

    def test_mcs_header_lowercase_with_dash(self):
        text = "mcs - Chapter 3 - page 12\nsome repeated footer phrase"
        assert _classify(text) == ChunkType.references_boilerplate

    def test_numbered_reference_list_heavy(self):
        text = (
            "[1] Smith, J. (2001). Introduction.\n"
            "[2] Jones, A. (2005). Advanced Topics.\n"
            "[3] Brown, R. (2010). Further Reading.\n"
            "[4] Green, N. (2015). Applications.\n"
        )
        assert _classify(text) == ChunkType.references_boilerplate

    def test_problems_for_section_heading(self):
        text = "Problems for Section 3.2\n\nSolve the following recurrences.\n"
        assert _classify(text) == ChunkType.references_boilerplate

    def test_further_reading_heading(self):
        text = "\nFurther Reading\n\nSee also chapters 5 and 6 of Cormen et al.\n"
        assert _classify(text) == ChunkType.references_boilerplate

    def test_review_problems_heading(self):
        text = "\nReview Problems\n\nProblem 1: Prove by induction that...\n"
        assert _classify(text) == ChunkType.references_boilerplate

    def test_instructional_text_not_flagged(self):
        """A references list embedded in a larger instructional paragraph must
        not cause the whole chunk to be mis-classified if it's mostly content."""
        text = (
            "In graph theory, a connected graph is one in which there exists "
            "a path between every pair of vertices.  Euler proved that a graph "
            "has an Eulerian circuit if and only if every vertex has even degree.  "
            "This result is foundational in combinatorics and has applications "
            "in network routing, DNA sequencing, and algorithm design.  It also "
            "underpins the Chinese Postman Problem studied in operational research."
        )
        # No reference/boilerplate signals → must stay instructional
        assert _classify(text) == ChunkType.instructional


# ── EXERCISE ─────────────────────────────────────────────────────────────────


class TestExercise:
    def test_problem_N_prefix(self):
        text = "Problem 1\nLet G = (V, E) be a simple graph.  Find the minimum spanning tree.\n"
        assert _classify(text) == ChunkType.exercise

    def test_exercise_N_prefix(self):
        text = "Exercise 5\nProve by induction that the sum of the first n integers equals n(n+1)/2.\n"
        assert _classify(text) == ChunkType.exercise

    def test_sub_part_labels(self):
        text = (
            "Solve each of the following:\n"
            "(a) Find all prime factors of 360.\n"
            "(b) Determine whether 1001 is prime.\n"
            "(c) Evaluate gcd(48, 180) using the Euclidean algorithm.\n"
            "(d) Show that there are infinitely many primes.\n"
        )
        assert _classify(text) == ChunkType.exercise

    def test_short_exercise_with_imperatives(self):
        text = (
            "Problem 3\n"
            "Calculate the determinant of the given 3×3 matrix.\n"
            "Verify your answer by row-reducing to echelon form.\n"
            "Find the eigenvalues if they exist.\n"
        )
        assert _classify(text) == ChunkType.exercise

    def test_long_instructional_text_not_exercise(self):
        """Longer text dominated by explanation should not be EXERCISE even
        if it contains a few imperative verbs like 'find' or 'show'."""
        text = (
            "A spanning tree of a connected graph G is a subgraph that includes "
            "all the vertices of G and is itself a tree.  Kruskal's algorithm builds "
            "the MST by sorting all edges by weight and adding the cheapest edge "
            "that does not form a cycle.  We can show that this greedy choice is "
            "optimal via a cut-property argument.  Find us a graph with a unique MST "
            "and you will notice the algorithm terminates in O(E log E) time.  "
            "This makes it very practical for dense graphs encountered in practice.  "
            "The algorithm was developed by Joseph Kruskal in 1956 and remains one "
            "of the most widely taught examples of a greedy algorithm in computer "
            "science courses worldwide, appearing in virtually every algorithms textbook."
        )
        # Long text — below EXERCISE threshold or outweighed by instructional context
        result = _classify(text)
        assert result == ChunkType.instructional


# ── INSTRUCTIONAL (default) ───────────────────────────────────────────────────


class TestInstructional:
    def test_empty_string(self):
        ct, score, rules = classify_chunk_type("")
        assert ct == ChunkType.instructional
        assert score == 0
        assert rules == []

    def test_whitespace_only(self):
        assert _classify("   \n\n\t  ") == ChunkType.instructional

    def test_typical_definition_chunk(self):
        text = (
            "A binary tree is a tree data structure in which each node has at "
            "most two children, referred to as the left child and the right child.  "
            "The topmost node is called the root.  Nodes without children are "
            "called leaves.  Binary trees are used to implement binary search trees "
            "and binary heaps, and are used for efficient sorting and searching."
        )
        assert _classify(text) == ChunkType.instructional

    def test_theorem_chunk(self):
        text = (
            "Theorem 2.4 (Euler's formula).  For any connected planar graph, "
            "V − E + F = 2, where V is the number of vertices, E is the number "
            "of edges, and F is the number of faces (including the outer face)."
        )
        assert _classify(text) == ChunkType.instructional

    def test_proof_chunk(self):
        text = (
            "Proof.  We proceed by induction on the number of edges E.  "
            "Base case: a tree with V vertices has E = V−1 and F = 1 (just the "
            "outer face), so V − E + F = V − (V−1) + 1 = 2. ∎"
        )
        assert _classify(text) == ChunkType.instructional


# ── PRIORITY ORDER ────────────────────────────────────────────────────────────


class TestPriorityOrder:
    def test_admin_beats_exercise(self):
        """A chunk with both markscheme signals and problem-statement signals
        must be classified as ADMIN_ASSESSMENT (higher priority)."""
        text = (
            "Mark scheme  —  Internal Assessment  —  Paper 1\n"
            "Problem 1: worth 10 marks.  Duration: 20 min.\n"
            "Award 3 marks for correct factorisation.\n"
            "(a) Find the roots.  (b) Verify your answer.  (c) Show working.\n"
        )
        assert _classify(text) == ChunkType.admin_assessment

    def test_references_beats_exercise(self):
        """A 'Problems for Section X' heading makes the chunk REFERENCES_BOILERPLATE,
        not EXERCISE, because it fires the boilerplate rule first."""
        text = "Problems for Section 4.1\nProblem 1: ...\n"
        assert _classify(text) == ChunkType.references_boilerplate

    def test_score_and_rules_returned(self):
        text = "References\n\n[1] Cormen et al. Introduction to Algorithms.\n"
        ct, score, rules = classify_chunk_type(text)
        assert ct == ChunkType.references_boilerplate
        assert score > 0
        assert any("references" in r for r in rules)
