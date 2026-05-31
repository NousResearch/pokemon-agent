//! `.npz` candidate-cache I/O, compatible with the Python `np.savez` layout:
//! scalars `species,tid,sid` + arrays `G(u64) pid(u64) nature(u8) iters(i32)
//! o1..o4(u16)`.

use std::fs::File;
use std::path::Path;

use ndarray::{Array0, Array1, Ix1};
use ndarray_npy::{NpzReader, NpzWriter};

use crate::enumerate::Candidate;

type BoxErr = Box<dyn std::error::Error>;

/// A loaded candidate set (columnar, as stored on disk).
#[derive(Clone, Debug, Default)]
pub struct CandidateSet {
    pub species: i64,
    pub tid: i64,
    pub sid: i64,
    pub g: Vec<u64>,
    pub pid: Vec<u64>,
    pub nature: Vec<u8>,
    pub iters: Vec<i32>,
    pub o1: Vec<u16>,
    pub o2: Vec<u16>,
    pub o3: Vec<u16>,
    pub o4: Vec<u16>,
}

impl CandidateSet {
    pub fn len(&self) -> usize {
        self.g.len()
    }
    pub fn is_empty(&self) -> bool {
        self.g.is_empty()
    }

    /// Row `i` as a [`Candidate`] (for differential checks against `enum_candidate`).
    pub fn candidate(&self, i: usize) -> Candidate {
        Candidate {
            g: self.g[i] as u32,
            pid: self.pid[i] as u32,
            nature: self.nature[i],
            iters: self.iters[i] as u32,
            o1: self.o1[i],
            o2: self.o2[i],
            o3: self.o3[i],
            o4: self.o4[i],
        }
    }
}

fn scalar_i64(r: &mut NpzReader<File>, name: &str) -> i64 {
    r.by_name::<ndarray::OwnedRepr<i64>, ndarray::Ix0>(name)
        .map(|a: Array0<i64>| a.into_scalar())
        .unwrap_or(0)
}

fn col<T: ndarray_npy::ReadableElement + Clone>(
    r: &mut NpzReader<File>,
    name: &str,
) -> Result<Vec<T>, BoxErr> {
    let a: Array1<T> = r.by_name::<ndarray::OwnedRepr<T>, Ix1>(name)?;
    Ok(a.to_vec())
}

/// Load a `.npz` candidate cache written by the Python pipeline (or by [`save`]).
pub fn load(path: impl AsRef<Path>) -> Result<CandidateSet, BoxErr> {
    let mut r = NpzReader::new(File::open(path)?)?;
    Ok(CandidateSet {
        species: scalar_i64(&mut r, "species"),
        tid: scalar_i64(&mut r, "tid"),
        sid: scalar_i64(&mut r, "sid"),
        g: col(&mut r, "G")?,
        pid: col(&mut r, "pid")?,
        nature: col(&mut r, "nature")?,
        iters: col(&mut r, "iters")?,
        o1: col(&mut r, "o1")?,
        o2: col(&mut r, "o2")?,
        o3: col(&mut r, "o3")?,
        o4: col(&mut r, "o4")?,
    })
}

/// Write candidates to a `.npz` with the same keys/dtypes as the Python cache.
pub fn save(
    path: impl AsRef<Path>,
    cands: &[Candidate],
    species: i64,
    tid: i64,
    sid: i64,
) -> Result<(), BoxErr> {
    let mut w = NpzWriter::new(File::create(path)?);
    w.add_array("species", &Array0::from_elem((), species))?;
    w.add_array("tid", &Array0::from_elem((), tid))?;
    w.add_array("sid", &Array0::from_elem((), sid))?;
    w.add_array("G", &Array1::from_iter(cands.iter().map(|c| c.g as u64)))?;
    w.add_array(
        "pid",
        &Array1::from_iter(cands.iter().map(|c| c.pid as u64)),
    )?;
    w.add_array("nature", &Array1::from_iter(cands.iter().map(|c| c.nature)))?;
    w.add_array(
        "iters",
        &Array1::from_iter(cands.iter().map(|c| c.iters as i32)),
    )?;
    w.add_array("o1", &Array1::from_iter(cands.iter().map(|c| c.o1)))?;
    w.add_array("o2", &Array1::from_iter(cands.iter().map(|c| c.o2)))?;
    w.add_array("o3", &Array1::from_iter(cands.iter().map(|c| c.o3)))?;
    w.add_array("o4", &Array1::from_iter(cands.iter().map(|c| c.o4)))?;
    w.finish()?;
    Ok(())
}
