function test_seed_runner(platemoRoot,outputRoot)
% 同 seed 重放真实平台；比较搜索结果和指标，不比较运行时间/文件 hash。
    assert(isfolder(outputRoot),'Create a fresh output directory first.');
    cd(platemoRoot);
    before = rng;
    cfg = struct('algorithms',{{struct('class','NSGAII','label','ga','params',[]), ...
        struct('class','NSGAIII','label','reference','params',[])}}, ...
        'problems',{{struct('class','DTLZ2','M',3,'D',8)}}, ...
        'N',12,'maxFE',24,'runs',3,'metrics',{{'IGD','HV'}},'save_count',2, ...
        'seeds',[11,22,33],'experiment_root',outputRoot,'experiment_id','seed_old');
    path = fullfile(outputRoot,'seed_config.json');
    writeConfig(path,cfg);
    run_platemo_batch(path);
    assert(isequal(before,rng),'Runner must restore caller MATLAB RNG state.');
    cfg.experiment_id = 'seed_new';
    cfg.algorithms = fliplr(cfg.algorithms);
    writeConfig(path,cfg);
    run_platemo_batch(path);
    compareResults(outputRoot,'seed_old','seed_new');
    % 不同 seed 必须影响真实搜索结果，避免只记录 seed 而没有设置。
    cfg.experiment_id = 'seed_different';
    cfg.seeds = [44,55,66];
    writeConfig(path,cfg);
    run_platemo_batch(path);
    first = firstPopulation(outputRoot,'seed_new');
    other = firstPopulation(outputRoot,'seed_different');
    assert(~isequal(first,other),'Different seeds must affect the population.');
    cfg.seeds = [1,1,2];
    cfg.experiment_id = 'duplicate_seed';
    writeConfig(path,cfg);
    rejected = false;
    try, run_platemo_batch(path); catch ME, rejected = contains(ME.message,'seeds must contain'); end
    assert(rejected && ~isfolder(fullfile(outputRoot,cfg.experiment_id)));
    % 真实 SET 重放，验证 CPU/CUDA 的模型初始化、训练和预测噪声。
    cfg.algorithms = {struct('class','SET_NSGAIII','params',[2,2])};
    cfg.problems = {struct('class','DTLZ2','M',2,'D',5)};
    cfg.N = 6; cfg.maxFE = 42; cfg.runs = 1; cfg.seeds = 17;
    cfg.experiment_id = 'set_seed_old';
    writeConfig(path,cfg);
    run_platemo_batch(path);
    cfg.experiment_id = 'set_seed_new';
    writeConfig(path,cfg);
    run_platemo_batch(path);
    compareResults(outputRoot,'set_seed_old','set_seed_new');
    assert(isequal(before,rng));
    fprintf('SEED_RUNNER_TEST_PASS ordinary_replay=6 algorithm_order_independent=1 different_seed_effective=1 duplicate_rejected=1 SET_replay=1 matlab_state_restored=1\n');
end

function compareResults(root,oldId,newId)
    old = jsondecode(fileread(fullfile(root,oldId,'manifest.json')));
    fresh = jsondecode(fileread(fullfile(root,newId,'manifest.json')));
    for i = 1:numel(old.records)
        record = itemAt(old.records,i);
        match = [];
        for j = 1:numel(fresh.records)
            next = itemAt(fresh.records,j);
            if strcmp(record.label,next.label) && record.M == next.M && record.D == next.D && record.seed == next.seed
                match = next; break;
            end
        end
        assert(~isempty(match),'Replay record is missing.');
        a = load(fullfile(root,oldId,record.file));
        b = load(fullfile(root,newId,match.file));
        assert(isequaln(a.result{end,2}.decs,b.result{end,2}.decs),'Same seed produced different decisions.');
        assert(isequaln(a.result{end,2}.objs,b.result{end,2}.objs),'Same seed produced different objectives.');
        assert(isequaln(a.metric.IGD,b.metric.IGD) && isequaln(a.metric.HV,b.metric.HV),'Same seed produced different IGD/HV.');
        assert(record.seed == a.experiment_info.seed && record.randomness.matlab.initialized_before_problem);
        if strcmp(record.algorithm,'SET_NSGAIII')
            assert(record.randomness.python.seed == record.seed && record.randomness.python.deterministic_algorithms);
        end
    end
end

function value = firstPopulation(root,id)
    manifest = jsondecode(fileread(fullfile(root,id,'manifest.json')));
    record = itemAt(manifest.records,1);
    data = load(fullfile(root,id,record.file));
    value = data.result{end,2}.decs;
end

function value = itemAt(items,index)
    if iscell(items), value = items{index}; else, value = items(index); end
end

function writeConfig(path,cfg)
    fid = fopen(path,'w','n','UTF-8');
    assert(fid >= 0,'Cannot create test config.');
    guard = onCleanup(@()fclose(fid)); %#ok<NASGU>
    fprintf(fid,'%s',jsonencode(cfg));
end
