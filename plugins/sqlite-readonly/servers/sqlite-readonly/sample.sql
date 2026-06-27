-- Sample dataset for the zero-config default. A tiny company directory so the server
-- works out of the box (no DB to configure): list tables, describe, query, ask in NL.
CREATE TABLE departments (
    id    INTEGER PRIMARY KEY,
    name  TEXT NOT NULL
);

CREATE TABLE employees (
    id            INTEGER PRIMARY KEY,
    name          TEXT NOT NULL,
    department_id INTEGER REFERENCES departments(id),
    title         TEXT,
    salary        INTEGER,
    hired_on      TEXT
);

INSERT INTO departments (id, name) VALUES
    (1, 'Engineering'),
    (2, 'Sales'),
    (3, 'Operations');

INSERT INTO employees (id, name, department_id, title, salary, hired_on) VALUES
    (1, 'Ada Lovelace',     1, 'Principal Engineer', 185000, '2021-03-01'),
    (2, 'Alan Turing',      1, 'Staff Engineer',      170000, '2020-07-15'),
    (3, 'Grace Hopper',     1, 'Engineering Manager', 195000, '2019-01-20'),
    (4, 'Katherine Johnson',2, 'Account Executive',   120000, '2022-05-10'),
    (5, 'Mary Jackson',     2, 'Sales Lead',          140000, '2021-11-02'),
    (6, 'Dorothy Vaughan',  3, 'Operations Manager',  150000, '2018-09-30');
