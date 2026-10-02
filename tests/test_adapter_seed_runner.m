function test_adapter_seed_runner(platemoRoot,outputRoot)
% 仅验证可选适配器的外部随机流。
    assert(isfolder(outputRoot),'Create a fresh output directory first.');
    cd(platemoRoot);
    before = rng;
    cfg = struct('metrics',{{'IGD','HV'}},'save_count',2,'experiment_root',outputRoot);
    path = fullfile(outputRoot,'adapter_seed_config.json');
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
    fprintf('SEED_RUNNER_TEST_PASS SET_replay=1 matlab_state_restored=1\n');
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
